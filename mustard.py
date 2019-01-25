import base64
import collections
import datetime
import json
import os
import sys
import threading
import time
import pytz
from pprint import pprint
# Hack: Get gevent to do its monkeypatching as early as possible.
# I have no idea what this is actually doing, but if you let the
# patching happen automatically, it happens too late, and we get
# RecursionErrors and such. There's a helpful warning on startup.
from gevent import monkey; monkey.patch_all(subprocess=True)
from flask import Flask, request, redirect, session, url_for, g, render_template, jsonify, Response
from flask_sockets import Sockets
from authlib.client import OAuth1Session, OAuth2Session
import requests
from werkzeug.contrib.fixers import ProxyFix

try:
	import config
except ImportError:
	# Construct a config object out of the environment
	import config_sample as config
	failed = []
	# Hack: Some systems like to give us a DATABASE_URL instead of a DATABASE_URI
	if "DATABASE_URL" in os.environ: os.environ["DATABASE_URI"] = os.environ["DATABASE_URL"]
	for var in dir(config):
		if var.startswith("__"): continue # Ignore dunders
		if var in os.environ: setattr(config, var, os.environ[var])
		else: failed.append(var)
	if failed:
		print("Required config variables %s not found - see config_sample.py" % ", ".join(failed), file=sys.stderr)
		sys.exit(1)
	sys.modules["config"] = config # Make the config vars available elsewhere

import database
import utils
app = Flask(__name__)
app.secret_key = config.SESSION_SECRET or base64.b64encode(os.urandom(12))
scheduler = utils.Scheduler()
sockets = Sockets(app)
app.wsgi_app = ProxyFix(app.wsgi_app)

REQUIRED_SCOPES = "channel_editor user:edit:broadcast user_read" # Ensure that these are sorted

class TwitchDataError(Exception):
	def __init__(self, error):
		self.__dict__.update(error)
		super().__init__(error["message"])

def query(endpoint, *, token=None, method="GET", params=None, data=None, auto_refresh=True):
	# If this is called outside of a Flask request context, be sure to provide
	# the auth token, and set auto_refresh to False.
	if token is None:
		auth = "OAuth " + session["twitch_token"]
	elif token == "bearer":
		auth = "Bearer " + session["twitch_token"]
	elif token == "app":
		r = requests.post("https://id.twitch.tv/oauth2/token", data={
			"grant_type": "client_credentials",
			"client_id": config.CLIENT_ID, "client_secret": config.CLIENT_SECRET,
		})
		r.raise_for_status()
		data = r.json()
		auth = "Bearer " + data["access_token"]
		# TODO: Save the token so long as it's valid
		# expires = int(time.time()) + data["expires_in"] - 120
	else:
		auth = "OAuth " + token

	# 20190125: Default is currently kraken. Progressively convert to explicit
	# krakenification, then switch the default to helix. (Then progressively
	# change the requests themselves so we use helix everywhere.)
	if not endpoint.startswith(("kraken/", "helix/")): endpoint = "kraken/" + endpoint
	r = requests.request(method, "https://api.twitch.tv/" + endpoint,
		params=params, data=data, headers={
		"Accept": "application/vnd.twitchtv.v5+json",
		"Client-ID": config.CLIENT_ID,
		"Authorization": auth,
	})
	if auto_refresh and r.status_code == 401 and r.json()["message"] == "invalid oauth token":
		r = requests.post("https://id.twitch.tv/oauth2/token", data={
			"grant_type": "refresh_token",
			"refresh_token": session["twitch_refresh_token"],
			"client_id": config.CLIENT_ID, "client_secret": config.CLIENT_SECRET,
		})
		r.raise_for_status()
		resp = r.json()
		session["twitch_token"] = resp["access_token"]
		session["twitch_refresh_token"] = resp["refresh_token"]

		# Recurse for simplicity. Do NOT pass the original token, and be sure to
		# prevent infinite loops by disabling auto-refresh. Otherwise, pass-through.
		return query(endpoint, method=method, params=params, data=data, auto_refresh=False)
	if r.status_code == 403:
		# TODO: What if it *isn't* of this form??
		raise TwitchDataError(json.loads(r.json()["message"]))
	r.raise_for_status()
	if r.status_code == 204: return {}
	return r.json()

def get_all_tags():
	print("Fetching tags into cache...")
	t = time.time()
	cursor = ""
	all_tags = []
	seen = 0
	while cursor is not None:
		data = query("helix/tags/streams", params={"first": 100, "after": cursor}, token="app", auto_refresh=False)
		# with open("dump.json", "w") as f: json.dump(data, f)
		all_tags.extend(
			(tag["tag_id"], tag["localization_names"]["en-us"], tag["localization_descriptions"]["en-us"])
			for tag in data["data"] if not tag["is_auto"]
		)
		seen += len(data["data"])
		cursor = data["pagination"].get("cursor")
		print("Fetching more... %d/%d" % (len(all_tags), seen))
	database.replace_all_tags(all_tags)
	print(len(all_tags), "tags fetched. Time taken:", time.time() - t)

def format_time(tm, tz):
	"""Format a time_t in a human-readable way, based on the timezone"""
	if not tz:
		# Without a timezone, all we can do is say "in X seconds"
		tm -= int(time.time())
		if tm < 60: return "in %d seconds" % tm
		return "in %d:%02d" % (tm // 60, tm % 60)
	tm = datetime.datetime.fromtimestamp(tm, tz=pytz.timezone(tz))
	return tm.strftime("at %H:%M")

@app.route("/")
def mainpage():
	# NOTE: If we've *reduced* the required scopes, this will still force a re-login.
	# However, it'll be an easy login, as Twitch will recognize the existing auth.
	if "twitch_token" not in session or session.get("twitch_auth_scopes") != REQUIRED_SCOPES:
		return render_template("login.html")
	token = session["twitch_token"]
	user = session["twitch_user"]
	# TODO: Switch to the new API /helix/streams
	channel = query("channels/" + user["_id"])
	tags = query("helix/streams/tags", params={"broadcaster_id": user["_id"]})
	channel["tags"] = ", ".join(sorted(t["localization_names"]["en-us"] for t in tags["data"] if not t["is_auto"]))
	sched_tz, schedule = database.get_schedule(user["_id"])
	if "twitter_oauth" in session:
		auth = session["twitter_oauth"]
		username = auth["screen_name"]
		twitter = "Twitter connected: " + username
		cred = (auth["oauth_token"], auth["oauth_token_secret"])
		tweets = [(format_time(tm, sched_tz), id, args[1]) for tm, id, args in scheduler.search(send_tweet) if args[0] == cred]
	else:
		twitter = """<div id="login-twitter"><a href="/login-twitter"><img src="/static/Twitter_Social_Icon_Square_Color.svg" alt="Twitter logo"><div>Connect with Twitter</div></a></div>"""
		tweets = []
	error = session.get("last_error_message", "")
	session["last_error_message"] = ""
	return render_template("index.html",
		twitter=twitter, username=user["display_name"],
		channel=channel, error=error,
		setups=database.list_setups(user["_id"]),
		sched_tz=sched_tz, schedule=schedule,
		checklist=database.get_checklist(user["_id"]),
		timers=database.list_timers(user["_id"]),
		tweets=tweets,
	)

@app.route("/update", methods=["POST"])
def update():
	if "twitch_user" not in session:
		return redirect(url_for("mainpage"))
	user = session["twitch_user"]
	try:
		resp = query("channels/" + user["_id"], method="PUT", data={
			"channel[game]": request.form["category"],
			"channel[status]": request.form["title"],
		})
	except TwitchDataError as e:
		session["last_error_message"] = "Stream status update not accepted: " + e.message
		return redirect(url_for("mainpage"))

	if "tags" in request.form:
		# Convert tag names into IDs
		tags = tuple(t.strip() for t in request.form["tags"].split(","))
		tag_ids = database.get_tag_ids(tags)
		if len(tag_ids) != len(tags):
			session["last_error_message"] = "Tag names not all found in Twitch" # TODO: Make this error friendlier
			return redirect(url_for("mainpage"))
		try:
			resp = query("helix/streams/tags", method="PUT", token="bearer",
				params={"broadcaster_id": user["_id"]},
				data={"tag_ids": tag_ids},
			)
		except TwitchDataError as e:
			session["last_error_message"] = "Stream tags update not accepted: " + e.message

	return redirect(url_for("mainpage"))

@app.route("/schedule", methods=["POST"])
def update_schedule():
	if "twitch_user" not in session:
		return redirect(url_for("mainpage"))
	user = session["twitch_user"]
	# Perform simple validation on the schedule. Tidying up human entry
	# is the job of the front end; if you send "1pm" to the back end,
	# you will simply get back an error, nothing more. The front end is
	# supposed to have already converted this to "13:00", which is the
	# only format we accept here.
	schedule = []
	sched = "<unknown cause>" # in case we get an unexpected ValueError
	try:
		for day in range(7):
			sched = request.form.get("sched%d" % day, "")
			if ',' in sched: raise ValueError
			for time in sched.split():
				hr, min = time.split(":") # Raises ValueError if wrong number of colons
				if not (0 <= int(hr) < 24): raise ValueError # Also raises if not integer
				if not (0 <= int(min) < 60): raise ValueError
			schedule.append(" ".join(sched.split()))
	except ValueError:
		return "Schedule format error: " + sched, 400
	tz = request.form.get("sched_tz")
	if not tz:
		# No TZ specified? Use what we have, if possible, otherwise
		# demand one from the user. The front end will normally try
		# to provide a default timezone, so most users won't have
		# to worry about this.
		tz = database.get_schedule(user["_id"])[0]
		if not tz:
			return "Please specify a timezone", 400
	database.set_schedule(user["_id"], tz, schedule)
	return redirect(url_for("mainpage"))

@app.route("/checklist", methods=["POST"])
def update_checklist():
	if "twitch_user" not in session:
		return redirect(url_for("mainpage"))
	user = session["twitch_user"]
	database.set_checklist(user["_id"], request.form["checklist"].strip().replace("\r", ""))
	return redirect(url_for("mainpage"))

@app.route("/tweet", methods=["POST"])
def tweet():
	tweet = request.form.get("tweet")
	if not tweet or "twitter_oauth" not in session:
		return redirect(url_for("mainpage"))
	schedule = request.form.get("tweetschedule", "now")
	if schedule == "now":
		auth = session["twitter_oauth"]
		send_tweet((auth["oauth_token"], auth["oauth_token_secret"]), tweet)
		return redirect(url_for("mainpage"))
	schedule = int(schedule)
	target = database.get_next_event(session["twitch_user"]["_id"], schedule)
	if not target:
		# TODO: Catch this on the front end, so this ugly message won't
		# happen without someone messing around
		return "Can't schedule tweets without a schedule!", 400
	target += schedule
	if target - time.time() > 1800:
		# Protect against schedule mistakes and various forms of insanity
		# The half-hour limit aligns with the Heroku policy of shutting a
		# dyno down after 30 mins of inactivity, which means we guarantee
		# that this tweet will indeed happen prior to dyno sleep.
		# (Dyno sleep? Not the "Slumbering Dragon" from M13 methinks.)
		return "Refusing to schedule a tweet more than half an hour in advance", 400
	# TODO: Retain the tweet and token in Postgres in case the server restarts
	# We'll assume the token won't need changing - but we assume that already.
	# Keep the one-hour limit (give or take) to minimize the likelihood of the
	# token expiring. Don't fret the weirdnesses; if stuff breaks, be sure the
	# tweets get retained, and then let Twitter worry about deduplication - it
	# apparently isn't possible to post the same tweet twice. (Whodathunk?) So
	# if tweeting fails, check to see if it was "duplicate status", and if so,
	# remove the tweet from the database. (Otherwise, error means "try again",
	# unless we just want to schedule tweets as fire-and-forget.)
	auth = session["twitter_oauth"]
	scheduler.put(target, send_tweet, (auth["oauth_token"], auth["oauth_token_secret"]), tweet)
	return redirect(url_for("mainpage"))

def send_tweet(auth, tweet):
	"""Actually send a tweet"""
	twitter = OAuth1Session(config.TWITTER_CLIENT_ID, config.TWITTER_CLIENT_SECRET, auth[0], auth[1])
	resp = twitter.post("https://api.twitter.com/1.1/statuses/update.json", data={"status": tweet})
	if resp.status_code != 200:
		print("Unknown response from Twitter")
		print(resp.status_code)
		print("---")
		print(resp.json())
		print("---")
	# print("Tweet sent.")

@app.route("/deltweet/<int:id>")
def cancel_tweet(id):
	auth = session["twitter_oauth"]
	cred = (auth["oauth_token"], auth["oauth_token_secret"])
	for tm, i, args in scheduler.search(send_tweet):
		if args[0] == cred and id == i:
			scheduler.remove(id)
			return redirect(url_for("mainpage"))
	return "No such tweet to remove (might have already been sent)"

@app.route("/login")
def login():
	twitch = OAuth2Session(config.CLIENT_ID, config.CLIENT_SECRET,
		scope=REQUIRED_SCOPES)
	uri, state = twitch.authorization_url("https://id.twitch.tv/oauth2/authorize",
		redirect_uri=url_for("authorized", _external=True))
	session["login_state"] = state
	return redirect(uri)

@app.route("/login/authorized")
def authorized():
	if "error" in request.args:
		# User cancelled the auth flow - discard auth (most likely there won't be any)
		session.pop("twitch_token", None)
		return redirect(url_for("mainpage"))
	twitch = OAuth2Session(config.CLIENT_ID, config.CLIENT_SECRET,
		state=session["login_state"])
	resp = twitch.fetch_access_token("https://id.twitch.tv/oauth2/token",
		code=request.args["code"],
		# For some bizarre reason, we need to pass this information along.
		client_id=config.CLIENT_ID, client_secret=config.CLIENT_SECRET,
		redirect_uri=url_for("authorized", _external=True))
	if "access_token" not in resp:
		# Something went wrong with the retrieval. No idea what or why,
		# so I'm doing a cop-out and just dumping to console.
		print("Unable to log in")
		pprint(resp)
		print("Returning generic failure.")
		raise Exception
	session["twitch_token"] = resp["access_token"]
	session["twitch_refresh_token"] = resp["refresh_token"]
	session["twitch_auth_scopes"] = " ".join(sorted(resp["scope"]))
	user = query("user")
	database.create_user(user["_id"])
	session["twitch_user"] = user
	return redirect(url_for("mainpage"))

# TODO: This is dropping deprecation warnings regarding create_authorization_url and OAuth1
@app.route("/login-twitter")
def login_twitter():
	twitter = OAuth1Session(config.TWITTER_CLIENT_ID, config.TWITTER_CLIENT_SECRET,
		redirect_uri=url_for("authorized_twitter", _external=True))
	session["twitter_state"] = twitter.fetch_request_token("https://api.twitter.com/oauth/request_token")
	return redirect(twitter.authorization_url("https://api.twitter.com/oauth/authenticate"))

@app.route("/authorized-twitter")
def authorized_twitter():
	if "denied" in request.args:
		# User cancelled the auth flow - discard auth (most likely there won't be any)
		session.pop("twitter_oauth", None)
		return redirect(url_for("mainpage"))
	req_token = session["twitter_state"]
	twitter = OAuth1Session(config.TWITTER_CLIENT_ID, config.TWITTER_CLIENT_SECRET,
		req_token["oauth_token"], req_token["oauth_token_secret"])
	resp = twitter.fetch_access_token("https://api.twitter.com/oauth/access_token", request.args["oauth_verifier"])
	session["twitter_oauth"] = resp
	return redirect(url_for("mainpage"))

@app.route("/logout")
def logout():
	session.pop("twitch_token", None)
	session.pop("twitter_oauth", None)
	return redirect(url_for("mainpage"))

@app.route("/timer/new", methods=["POST"])
def create_timer():
	database.create_timer(session["twitch_user"]["_id"])
	return redirect(url_for("mainpage"))

@app.route("/timer/<id>")
def edit_timer(id):
	info = database.get_timer_details(session["twitch_user"]["_id"], id)
	if not info: return "Timer not found, or not owned by you", 404
	return render_template("timer.html", info=info)

def parse_time(timestr):
	"""Parse a human-writable time string into a number of seconds"""
	if not timestr: return 0
	if ":" not in timestr:
		return int(timestr)
	neg = timestr.startswith("-") # "-5:30" means -330 seconds
	min, sec = timestr.strip("-").split(":")
	time = int(min) * 60 + int(sec)
	if neg: return -time
	return time

@app.route("/timer/<id>", methods=["POST"])
def save_timer(id):
	database.update_timer_details(session["twitch_user"]["_id"], id,
		title=request.form["title"],
		delta=parse_time(request.form["delta"]),
		maxtime=parse_time(request.form["maxtime"]),
		styling=request.form["styling"],
	)
	return redirect(url_for("mainpage"))

@app.route("/countdown/<id>")
def countdown(id):
	info = database.get_public_timer_details(id)
	if not info: return "Timer not found", 404
	return render_template("countdown.html", id=id, **info)

# ---- Live search API ----

@app.route("/search/game")
def findgame():
	games = query("search/games", params={"query": request.args["q"], "type": "suggest"})
	return jsonify([{key: game[key] for key in ("name", "localized_name", "box")} for game in games["games"] or ()])

# ---- Config management API ----

@app.route("/api/hello")
def helloworld():
	if "twitch_user" in session:
		return jsonify({"user": session["twitch_user"]["display_name"]})
	return jsonify({"user": None})

@app.route("/api/setups")
def list_setups():
	return jsonify(database.list_setups(session["twitch_user"]["_id"]))

@app.route("/api/setups", methods=["POST"])
def create_setup():
	if not request.json: return jsonify({}), 400
	missing = {"category", "title"} - set(request.json)
	if missing:
		return jsonify({"error": "Missing: " + ", ".join(sorted(missing))}), 400
	setup = database.create_setup(session["twitch_user"]["_id"], **request.json)
	return jsonify(setup)

@app.route("/api/setups/<int:setupid>", methods=["DELETE"])
def delete_setup(setupid):
	deleted = database.delete_setup(session["twitch_user"]["_id"], setupid)
	if deleted: return "", 204
	return "", 404

@app.route("/mustard-backup.json")
def make_backup():
	twitchid = session["twitch_user"]["_id"]
	response = "{\n"
	# Setups
	setups = database.list_setups(twitchid)
	response += '\t"setups": [\n'
	fields = "category", "title", "tags", "tweet"
	for setup in setups:
		setup = {field: setup[field] for field in fields}
		response += "\t\t" + json.dumps(setup) + ",\n"
	response += '\t\t""\n\t],\n'
	# Schedule
	tz, sched = database.get_schedule(twitchid)
	response += '\t"schedule": [\n'
	for day in sched:
		response += "\t\t" + json.dumps(day) + ",\n"
	response += "\t\t" + json.dumps(tz) + "\n\t],\n"
	# Checklist
	checklist = database.get_checklist(twitchid).strip().split("\n")
	response += '\t"checklist": [\n'
	for item in checklist:
		response += "\t\t" + json.dumps(item) + ",\n"
	response += '\t\t""\n\t],\n' # Empty string as shim. Ignored on import.
	# Timers
	timers = database.list_timers(twitchid, full=True)
	response += '\t"timers": [\n'
	for timer in timers:
		item = dict(zip("id title delta maxtime styling".split(), timer))
		response += "\t\t" + json.dumps(item) + ",\n"
	response += '\t\t""\n\t],\n'
	# Footer (marker to show that the file was correctly downloaded)
	# This must NOT include any sort of timestamp, as the backup file
	# must be completely stable (taking two backups without changing
	# anything should result in bit-for-bit identical files).
	response += '\t"": "Mustard-Mine Backup"\n}\n'
	return Response(response, mimetype="application/json",
		headers={"Content-disposition": "attachment"})

@app.route("/restore-backup", methods=["POST"])
def restore_backup():
	twitchid = session["twitch_user"]["_id"]
	if not twitchid:
		return redirect(url_for("mainpage"))
	try:
		data = json.loads(request.files["backup"].read().decode("utf-8"))
	except (KeyError, UnicodeDecodeError, json.JSONDecodeError):
		return "Backup file unreadable - must be a JSON file saved from Mustard Mine.", 400
	# Signature (from footer)
	if data[""] != "Mustard-Mine Backup":
		return "Backup file corrupt - signature missing.", 400
	# Open a single database transaction and do all the work.
	with database.Restorer(twitchid) as r:
		if "setups" in data:
			r.wipe_setups()
			for setup in data["setups"]:
				if setup == "": continue # The shim at the end
				if "communities" in setup:
					# Previously, Twitch had "communities", which no longer do anything.
					# Silently remove them from the data.
					del setup["communities"]
				r.check_dict(setup)
				r.restore_setup(**setup)
		if "schedule" in data:
			sched = data["schedule"]
			if not isinstance(sched, list) or len(sched) != 8: r.fail()
			r.restore_schedule(sched[-1], sched[:-1])
		if "checklist" in data:
			checklist = data["checklist"]
			if isinstance(checklist, list): checklist = "\n".join(checklist).strip()
			if not isinstance(checklist, str): r.fail()
			r.restore_checklist(checklist)
		if "timers" in data:
			# This one is problematic. We can't simply wipe and recreate because IDs
			# are significant (they're the external references, so people's OBS configs
			# will have those same IDs in them).
			for timer in data["timers"]:
				if timer == "": continue # The shim
				r.check_dict(timer)
				r.restore_timer(**timer)
			r.wipe_untouched_timers()
	return '<ul><li>%s</li></ul><a href="/">Back</a>' % r.summary.strip().replace("\n", "</li><li>"), 400 if r.failed else 200

@app.route("/tz")
def tz():
	return """
<div id=tz></div>
<script>
const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
document.getElementById("tz").innerHTML = "Your timezone appears to be: " + tz;
</script>
"""

# Map timer IDs to lists of sockets
timer_sockets = collections.defaultdict(list)
@sockets.route("/countdown_ctrl")
def control_socket(ws):
	timerid = None
	while not ws.closed:
		message = ws.receive()
		if type(message) is not str: continue # Be VERY strict here, for safety
		try: message = json.loads(message)
		except JSON.JSONDecodeError: continue
		if type(message) is not dict: continue # Again, very strict
		if "type" not in message: continue
		# Okay, we have a properly-formed message.
		if message["type"] == "init":
			if timerid: continue # Don't initialize twice
			if "id" not in message or not message["id"]: continue
			timerid = message["id"]
			timer_sockets[timerid].append(ws)
			ws.send(json.dumps({"type": "inited"}))
	if timerid: timer_sockets[timerid].remove(ws)

'''
# For testing, update a single timer
@app.route("/hack/<id>")
def hack_timer(id):
	# For never-used IDs, don't defaultdict a list into the mapping
	if id not in timer_sockets: return "Nobody's using that"
	for ws in timer_sockets[id]:
		ws.send(json.dumps({"type": "adjust", "delta": 60}))
	return "Done"
@app.route("/force/<id>")
def force_timer(id):
	# For never-used IDs, don't defaultdict a list into the mapping
	if id not in timer_sockets: return "Nobody's using that"
	for ws in timer_sockets[id]:
		ws.send(json.dumps({"type": "force", "time": 900}))
	return "Done"
'''

# Normally the one-click adjustments apply to ALL your timers
@app.route("/timer-adjust-all/<int:delta>")
@app.route("/timer-adjust-all/-<int:delta>", defaults={"negative": True})
def adjust_all_timers(delta, negative=False):
	if negative: delta = -delta # Since the int converter can't handle negatives, we do them manually.
	twitchid = session["twitch_user"]["_id"]
	if not twitchid: return redirect(url_for("mainpage"))
	for id, timer in database.list_timers(twitchid):
		if id in timer_sockets:
			for ws in timer_sockets[id]:
				ws.send(json.dumps({"type": "adjust", "delta": delta}))
	return "", 204

@app.route("/timer-force-all/<int:tm>")
def force_all_timers(tm):
	twitchid = session["twitch_user"]["_id"]
	if not twitchid: return redirect(url_for("mainpage"))
	for id, timer in database.list_timers(twitchid):
		if id in timer_sockets:
			for ws in timer_sockets[id]:
				ws.send(json.dumps({"type": "force", "time": tm}))
	return "", 204

if __name__ == "__main__":
	import logging
	logging.basicConfig(level=logging.INFO)
	# Load us up using gunicorn, configured via the Procfile
	with open("Procfile") as f: cmd = f.read().strip().replace("web: ", "")
	if "PORT" not in os.environ: os.environ["PORT"] = "5000" # hack - pick a different default port
	sys.argv = cmd.split(" ")[1:] # TODO: Split more smartly
	from gunicorn.app.wsgiapp import run; run()
else:
	# Worker startup. This is the place to put any actual initialization work
	# as it won't be done on master startup.
	if database.tags_need_updating():
		threading.Thread(target=get_all_tags).start()
