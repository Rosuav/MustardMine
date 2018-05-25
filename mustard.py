import base64
import json
import os
import sys
import time
from pprint import pprint
from flask import Flask, request, redirect, session, url_for, g, render_template, jsonify, Response
from flask_oauthlib.client import OAuth # deprecated - TODO: switch to authlib
from authlib.client import OAuth2Session
import requests

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

twitch = OAuth().remote_app('twitch',
	base_url='https://api.twitch.tv/kraken/',
	request_token_url=None,
	access_token_method='POST',
	access_token_url='https://api.twitch.tv/kraken/oauth2/token',
	authorize_url='https://api.twitch.tv/kraken/oauth2/authorize',
	consumer_key=config.CLIENT_ID,
	consumer_secret=config.CLIENT_SECRET,
	request_token_params={'scope': ["user_read", "channel_editor"]}
)
@twitch.tokengetter
def get_twitch_token(token=None):
	return session.get("twitch_token")

# TODO: Use this instead:
# twitch = OAuth2Session(config.CLIENT_ID, config.CLIENT_SECRET,
#	scope=["user_read", "channel_editor"])

twitter = OAuth().remote_app(
	'twitter',
	consumer_key=config.TWITTER_CLIENT_ID,
	consumer_secret=config.TWITTER_CLIENT_SECRET,
	base_url='https://api.twitter.com/1.1/',
	request_token_url='https://api.twitter.com/oauth/request_token',
	access_token_url='https://api.twitter.com/oauth/access_token',
	authorize_url='https://api.twitter.com/oauth/authenticate',
)
@twitter.tokengetter
def get_twitter_token():
	if "twitter_oauth" in session:
		resp = session["twitter_oauth"]
		return resp['oauth_token'], resp['oauth_token_secret']

def query(endpoint, *, token=None, method="GET", params=None, data=None, auto_refresh=True):
	# If this is called outside of a Flask request context, be sure to provide
	# the auth token, and set auto_refresh to False.
	if token is None:
		token = session["twitch_token"]
	r = requests.request(method, "https://api.twitch.tv/kraken/" + endpoint,
		params=params, data=data, headers={
		"Accept": "application/vnd.twitchtv.v5+json",
		"Client-ID": config.CLIENT_ID,
		"Authorization": "OAuth " + token,
	})
	if auto_refresh and r.status_code == 401 and r.json()["message"] == "invalid oauth token":
		r = requests.post("https://id.twitch.tv/oauth2/token", data={
			"grant_type": "refresh_token",
			"refresh_token": session["twitch_refresh_token"],
			"client_id": config.CLIENT_ID, "client_secret": config.CLIENT_SECRET,
		})
		r.raise_for_status()
		data = r.json()
		session["twitch_token"] = data["access_token"]
		session["twitch_refresh_token"] = data["refresh_token"]
		# Recurse for simplicity. Do NOT pass the original token, and be sure to
		# prevent infinite loops by disabling auto-refresh. Otherwise, pass-through.
		return query(endpoint, method=method, params=params, data=data, auto_refresh=False)
	r.raise_for_status()
	if r.status_code == 204: return {}
	return r.json()

@app.route("/")
def mainpage():
	if "twitter_oauth" in session:
		username = session["twitter_oauth"]["screen_name"]
		twitter = "Twitter connected: " + username
	else:
		twitter = """<div id="login-twitter"><a href="/login-twitter"><img src="/static/Twitter_Social_Icon_Square_Color.svg" alt="Twitter logo"><div>Connect with Twitter</div></a></div>"""
	if "twitch_token" not in session:
		return render_template("login.html", twitter=twitter)
	token = session["twitch_token"]
	user = session["twitch_user"]
	channel = query("channels/" + user["_id"])
	communities = query("channels/" + user["_id"] + "/communities")
	for community in communities["communities"]:
		database.cache_community(community)
	commnames = [comm["name"] for comm in communities["communities"]]
	sched_tz, schedule = database.get_schedule(user["_id"])
	return render_template("index.html",
		twitter=twitter, username=user["display_name"],
		channel=channel, commnames=commnames,
		setups=database.list_setups(user["_id"]),
		sched_tz=sched_tz, schedule=schedule,
		checklist=database.get_checklist(user["_id"]),
		timers=database.list_timers(user["_id"]),
	)

@app.route("/update", methods=["POST"])
def update():
	if "twitch_user" not in session:
		return redirect(url_for("mainpage"))
	user = session["twitch_user"]
	resp = query("channels/" + user["_id"], method="PUT", data={
		"channel[game]": request.form["category"],
		"channel[status]": request.form["title"],
	})
	communities = []
	for i in range(1, 4):
		name = request.form.get("comm%d" % i)
		if name == "": continue
		community_id = database.get_community_id(name)
		if community_id is None:
			resp = query("communities", params={"name": name})
			community_id = resp["_id"]
			database.cache_community(resp)
		communities.append(community_id)
	query("channels/" + user["_id"] + "/communities", method="PUT", data={
		"community_ids[]": communities,
	})
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
		send_tweet(get_twitter_token(), tweet)
		return redirect(url_for("mainpage"))
	schedule = int(schedule)
	target = database.get_next_event(session["twitch_user"]["_id"], schedule)
	if not target:
		# TODO: Catch this on the front end, so this ugly message won't
		# happen without someone messing around
		return "Can't schedule tweets without a schedule!", 400
	target += schedule
	if target - time.time() > 3600:
		# Protect against schedule mistakes and various forms of insanity
		return "Refusing to schedule a tweet more than an hour in advance", 400
	# TODO: Retain the tweet and token in Postgres in case the server restarts
	# We'll assume the token won't need changing - but we assume that already.
	# Keep the one-hour limit (give or take) to minimize the likelihood of the
	# token expiring. Don't fret the weirdnesses; if stuff breaks, be sure the
	# tweets get retained, and then let Twitter worry about deduplication - it
	# apparently isn't possible to post the same tweet twice. (Whodathunk?) So
	# if tweeting fails, check to see if it was "duplicate status", and if so,
	# remove the tweet from the database. (Otherwise, error means "try again",
	# unless we just want to schedule tweets as fire-and-forget.)
	scheduler.put(target, send_tweet, get_twitter_token(), tweet)
	return redirect(url_for("mainpage"))

def send_tweet(auth, tweet):
	"""Actually send a tweet"""
	resp = twitter.post("statuses/update.json", data={"status": tweet}, token=auth)
	if resp.status != 200:
		try:
			return jsonify(resp.data["errors"][0]), resp.status
		except:
			# If something goes wrong, provide more info on the console
			print("Unknown response from Twitter")
			print(resp.status)
			print("---")
			print(resp.data)
			print("---")
			raise
	# print("Tweet sent.")

@app.route("/login")
def login():
	return twitch.authorize(callback=url_for("authorized", _external=True))
	# TODO:
	#uri, state = twitch.authorization_url("https://api.twitch.tv/kraken/oauth2/authorize",
	#	redirect_uri=url_for("authorized", _external=True))
	#session["login_state"] = state
	#return redirect(uri)

@app.route("/login/authorized")
def authorized():
	# TODO:
	#token = twitch.fetch_access_token("https://api.twitch.tv/kraken/oauth2/token",
	#	code=request.args["code"], state=session["login_state"])
	resp = twitch.authorized_response()
	if resp is None:
		return "Access denied: reason=%s error=%s" % (
			request.args['error'],
			request.args['error_description']
		)
	session["twitch_token"] = resp["access_token"]
	session["twitch_refresh_token"] = resp["refresh_token"]
	user = query("user")
	database.create_user(user["_id"])
	session["twitch_user"] = user
	return redirect(url_for("mainpage"))

@app.route("/login-twitter")
def login_twitter():
	return twitter.authorize(callback=url_for("authorized_twitter", _external=True))

@app.route("/authorized-twitter")
def authorized_twitter():
	resp = twitter.authorized_response()
	if resp is not None:
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
	# TODO: Have the page query the server periodically, or maybe even open
	# a websocket. It can then get notified of timer adjustments.
	info = database.get_public_timer_details(id)
	if not info: return "Timer not found", 404
	return render_template("countdown.html", id=id, **info)

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
	missing = {"category", "title", "communities"} - set(request.json)
	if missing:
		return jsonify({"error": "Missing: " + ", ".join(sorted(missing))}), 400
	for name in request.json["communities"]:
		if database.get_community_id(name) is None:
			resp = query("communities", params={"name": name})
			database.cache_community(resp)
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
	fields = "category", "title", "communities", "tweet"
	for setup in setups:
		setup = {field: setup[field] for field in fields}
		response += "\t\t" + json.dumps(setup) + ",\n"
	response += '\t\t"shim [TODO]"\n\t],\n'
	# Schedule
	tz, sched = database.get_schedule(twitchid)
	response += '\t"schedule": [\n'
	for day in sched:
		response += "\t\t" + json.dumps(day) + ",\n"
	response += "\t\t" + json.dumps(tz) + "\n\t],\n"
	# Footer (marker to show that the file was correctly downloaded)
	# This must NOT include any sort of timestamp, as the backup file
	# must be completely stable (taking two backups without changing
	# anything should result in bit-for-bit identical files).
	response += '\t"": "Mustard-Mine Backup"\n}\n'
	return Response(response, mimetype="application/json",
		headers={"Content-disposition": "attachment"})

@app.route("/tz")
def tz():
	return """
<div id=tz></div>
<script>
const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
document.getElementById("tz").innerHTML = "Your timezone appears to be: " + tz;
</script>
"""

if __name__ == "__main__":
	import logging
	logging.basicConfig(level=logging.INFO)
	app.run(host='0.0.0.0')
