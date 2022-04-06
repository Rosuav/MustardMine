import base64
import collections
import datetime
import functools
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
from flask import Flask, request, redirect, session, url_for, g, render_template, jsonify, Response, Markup
from flask_sockets import Sockets
from authlib.integrations.requests_client import OAuth1Session, OAuth2Session
import requests

# Flask_Sockets 0.2.1 with Werkzeug 2.0.0+ breaks on all websocket connections due to
# a mismatch of routing rules. The websocket rules need to be identified correctly.
from werkzeug.routing import Rule
class Sockets(Sockets):
	def add_url_rule(self, rule, _, f, **options):
		self.url_map.add(Rule(rule, endpoint=f, websocket=True))

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

# Override Flask's forcing of Location headers to be absolute, since it
# gets stuff flat-out wrong. Also, the spec now says that relative
# headers are fine (and even when the spec said that the Location should
# to be absolute, everyone accepted relative URIs).
if os.environ.get("OVERRIDE_REDIRECT_HTTPS"):
	from werkzeug.middleware.proxy_fix import ProxyFix
	app.wsgi_app = ProxyFix(app.wsgi_app) # Grab info from Forwarded headers
	_redirect = redirect
	def redirect(*a, **kw):
		resp = _redirect(*a, **kw)
		resp.autocorrect_location_header = False
		return resp
	_url_for = url_for
	def url_for(*a, **kw): return _url_for(*a, **kw).replace("http://", "https://")

# TODO: Ensure that all the Helix scopes are listed here. Until the shutdown,
# the Kraken scopes will be treated as valid (eg "user_read" grants permissions to
# the Helix APIs that want "user:read:email" permission - but "user:edit:broadcast"
# should imply that too), but ideally, we should be requesting the Helix scopes in
# addition to the Kraken ones, so that the shutdown can simply have us remove some.
REQUIRED_SCOPES = "channel:manage:broadcast channel_editor user:edit:broadcast user_read" # Ensure that these are sorted

class TwitchDataError(Exception):
	def __init__(self, error):
		self.__dict__.update(error)
		super().__init__(error["message"])

def query(endpoint, *, token, method="GET", params=None, data=None, auto_refresh=True):
	# If this is called outside of a Flask request context, be sure to provide
	# the auth token, and set auto_refresh to False.
	# TODO: Tidy up all this mess of auth patterns. It'll probably be easiest
	# to migrate everything to Helix first, and then probably everything will
	# use Bearer or App authentication.
	if token is None:
		auth = None
	elif token == "oauth":
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
		auth = "OAuth " + token # Not currently used anywhere

	# 20190212: All endpoints should have explicit API selection. After a
	# while, change so the default is helix. (Then progressively
	# change the requests themselves so we use helix everywhere.)
	# 20200619: The few remaining Kraken calls are all relating to a current
	# failure in PATCH /helix/channels to use editor privileges, so that may
	# soon be fixed and then we can finally go Helix-exclusive!
	if not endpoint.startswith(("kraken/", "helix/")): raise ValueError("Need explicit selection of API (helix or kraken)")
	# if not endpoint.startswith(("kraken/", "helix/")): endpoint = "helix/" + endpoint
	r = requests.request(method, "https://api.twitch.tv/" + endpoint,
		params=params, data=data, headers={
		"Accept": "application/vnd.twitchtv.v5+json", # for Kraken only
		"Client-ID": config.CLIENT_ID,
		"Authorization": auth,
	})
	if auto_refresh and r.status_code == 401 and r.json()["message"].lower() == "invalid oauth token":
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
		# (But DO pass the token-passing mode.)
		return query(endpoint, token="bearer" if token == "bearer" else "oauth",
			method=method, params=params, data=data, auto_refresh=False)
	if r.status_code == 403:
		msg = r.json()["message"]
		try: msg = json.loads(msg)
		except json.JSONDecodeError: msg = {"message": str(msg)} # Some APIs return JSON messages, some don't.
		raise TwitchDataError(msg)
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

channel_editor_cache = {}
def may_edit_channel(userid, channelid):
	# Twitch will ensure that we have legit powers before making any actual
	# channel changes, but we need to guard the Mustard Mine setups themselves.
	# Unfortunately, we can't easily ask Twitch whether or not we have editor
	# access, short of making a change (a null edit doesn't count - it has to
	# actually specify a field to change). So we first query, then update, the
	# category. That's two additional API calls, so we cache it for 15 mins.
	# NOTE: Poking around on the dashboard shows this undocumented API endpoint:
	# https://api.twitch.tv/v5/permissions/channels/YOUR_ID/editable_channels
	# Whether this is useful or not remains to be seen. Needs OAuth and a
	# client-id, and maybe "Twitch-Api-Token: 1c8ad08632cc875c9af714fd6a9570da".
	if userid == channelid: return True # Trivially true
	if channel_editor_cache.get((userid, channelid), 0) > time.time():
		# The user was an editor when last seen, recently
		return True
	try:
		# TODO: Once editors are allowed to edit via Helix, find a way to probe
		# for support - probably the equivalent to this, but using Helix.
		# 20220218: It's still not working. So editor access is being disabled,
		# and these calls will fail.
		return False
		data = query("kraken/channels/%s" % channelid, method="GET", token=None)
		resp = query("kraken/channels/%s" % channelid, method="PUT", token="oauth", data={"channel[game]": data["game"]})
		channel_editor_cache[(userid, channelid)] = time.time() + 900
		return True
	except TwitchDataError as e:
		return False # If anything goes wrong, assume not permitted.
	return False # shouldn't happen

def wants_channelid(f):
	"""Wrap a routed function to provide a channel ID

	If the function returns a redirect to the main page, will mutate it.
	"""
	@functools.wraps(f)
	def handler(*a, **kw):
		userid = session["twitch_user"]["_id"]
		channelid = request.form.get("channelid") or request.args.get("channelid") or userid
		if not may_edit_channel(userid, channelid): return redirect(url_for("mainpage"))
		resp = f(*a, **kw, channelid=channelid)
		if (channelid != userid and
			getattr(resp, "status_code", None) == 302 and
			resp.location == url_for("mainpage")
		):
			return redirect(url_for("mainpage", channelid=channelid))
		return resp
	return handler

def list_scheduled_tweets(token, secret):
	cred = (token, secret)
	return [(format_time(tm, None), id, args[1]) for tm, id, args in scheduler.search(send_tweet) if args[0] == cred]

def get_channel_setup(channelid):
	channel = query("helix/channels?broadcaster_id=" + channelid, token="bearer")["data"][0]
	# For compatibility and convenience, provide _id as an alias for broadcaster_id.
	channel["_id"] = channel["broadcaster_id"]
	# 20200619: Temporary compatibility in case people have cached versions of the JS
	channel["game"] = channel["game_name"]; channel["status"] = channel["title"]
	tags = query("helix/streams/tags", params={"broadcaster_id": channelid}, token="app")
	channel["tags"] = ", ".join(sorted(t["localization_names"]["en-us"] for t in tags["data"] if not t["is_auto"]))
	# 20210108: Helix still doesn't carry the Mature flag. We could fetch that from Kraken,
	# but there's no way in either Kraken or Helix to update it, so it would just be an
	# advisory note to assist the streamer, and there's no way to keep it accurate. :(
	# It's currently checked only at time of setup update, and nowhere else.
	# 20210716: Still a problem. Have moaned here but we'll see if they do anything.
	# https://twitch.uservoice.com/forums/310213-developers/suggestions/42246544
	return channel

@app.route("/editor/<channelid>")
def no_editors_allowed(channelid):
	return """Due to the shutdown of Twitch's Kraken API and a bug in the Helix API, channel editors
		are no longer able to make changes using third-party tools. If this shutdown has affected
		you, please contact Rosuav and request a token-retention system as an alternative. This
		will require additional the broadcaster to grant additional permissions to the Mustard Mine,
		but would re-enable editor access to this page. We apologize for the inconvenience.""", 401

@app.route("/")
#@app.route("/editor/<channelid>") # Disabled until Twitch fix things
def mainpage(channelid=None):
	# NOTE: If we've *reduced* the required scopes, this will still force a re-login.
	# However, it'll be an easy login, as Twitch will recognize the existing auth.
	if "twitch_token" not in session or session.get("twitch_auth_scopes") != REQUIRED_SCOPES:
		return render_template("login.html")
	user = session["twitch_user"]
	if channelid is None: channelid = user["_id"]
	try: channelid = str(int(channelid))
	except ValueError:
		# If you go to /editor/somename, redirect to /editor/equivalent-id
		# Bookmarking the version with the ID will be slightly faster, but
		# streamers will usually want to share the version with the name.
		users = query("helix/users", token="app", params={"login": channelid})["data"]
		# users is either an empty list (bad login) or a list of one.
		if not users: return redirect("/")
		return redirect("/editor/" + users[0]["id"])
	if not may_edit_channel(user["_id"], channelid): return redirect(url_for("mainpage"))
	database.create_user(channelid) # Just in case, make sure the database has the basic structure
	channel = get_channel_setup(channelid)
	[sched_tweet] = database.get_twitter_config(channelid)
	if "twitter_oauth" in session:
		auth = session["twitter_oauth"]
		username = auth["screen_name"]
		twitter = "Twitter connected: " + username
		tweets = list_scheduled_tweets(auth["oauth_token"], auth["oauth_token_secret"])
	else:
		twitter = Markup("""<div id="login-twitter"><a href="/login-twitter"><img src="/static/Twitter_Social_Icon_Square_Color.svg" alt="Twitter logo"><div>Connect with Twitter</div></a></div>""")
		tweets = []
	error = session.get("last_error_message", "")
	session["last_error_message"] = ""
	return render_template("index.html",
		twitter=twitter, username=user["display_name"],
		channel=channel, channelid=channelid, error=error,
		setups=database.list_setups(channelid),
		checklist=database.get_checklist(channelid),
		timers=database.list_timers(channelid),
		sched_tweet=sched_tweet, tweets=tweets,
	)

def find_game_id(game_name, token="bearer"): # pass token="app" if no login - slower b/c we don't cache app tokens (yet)
	resp = query("helix/games", token=token, params={"name": game_name})["data"]
	if not resp: return None
	return resp[0]["id"]

def do_update(channelid, info):
	"""Update channel status (category, title, etc)

	Returns None if successful, else a string of error/warning text.
	"""
	# 20210716: Twitch is sunsetting the Kraken API in half a year. If all the issues previously
	# seen have been resolved, then this code will be all we need. We still lose the Mature flag,
	# but we kinda already didn't have it.
	try:
		gameid = info.get("game_id") or find_game_id(info["category"])
		resp = query("helix/channels?broadcaster_id=" + channelid, method="PATCH", data={
			"game_id": gameid,
			"title": info["title"],
		}, token="bearer")
	except requests.exceptions.HTTPError as e:
		if channelid != session["twitch_user"]["_id"]:
			# 20210716: This endpoint does not work for editors. For the moment, we can
			# repeat the request via Kraken, but that won't work post-Feb. See also:
			# https://twitch.uservoice.com/forums/310213-developers/suggestions/40863712
			# 20220218: It still doesn't. So this ain't gonna work. Disabling.
			return "Editors can't use Helix, contact Rosuav for more details."
			try:
				resp = query("kraken/channels/" + channelid, method="PUT", data={
					"channel[game]": info["category"],
					"channel[status]": info["title"],
				}, token="oauth")
			except TwitchDataError as e:
				return "Stream status update not accepted: " + e.message
		else:
			try: return "Error updating stream status: " + e.message
			except AttributeError:
				print(e)
				return "Unknown error updating stream status (see server log)"
	except TwitchDataError as e:
		return "Stream status update not accepted: " + e.message

	ret = None
	if "tags" in info:
		# Convert tag names into IDs
		tags = tuple(t.strip() for t in info["tags"].split(",") if t.strip())
		if len(tags) > 5: # (magic number 5 is the Twitch limit)
			# Note that the saved setup will include all of them.
			# Maybe some day I'll have a UI for prioritizing tags, and
			# then have an easy way to turn one off (eg "Warming Up")
			# such that the next one along appears.
			ret = "%d tags used, first five kept" % len(tags) # Warning, not error
			tags = tags[:5]
		tag_ids = tags and database.get_tag_ids(tags)
		if len(tag_ids) != len(tags):
			return "Tag names not all found in Twitch" # TODO: Make this error friendlier
		try:
			resp = query("helix/streams/tags", method="PUT", token="bearer",
				params={"broadcaster_id": channelid},
				data={"tag_ids": tag_ids},
			)
		except TwitchDataError as e:
			return "Stream tags update not accepted: " + e.message

	return ret

@app.route("/update", methods=["POST"])
@wants_channelid
def update(channelid):
	if "twitch_user" not in session:
		return redirect(url_for("mainpage"))
	err = do_update(channelid, request.form)
	if err: session["last_error_message"] = err
	return redirect(url_for("mainpage"))

@app.route("/api/update", methods=["POST"])
@wants_channelid
def api_update(channelid):
	setup = get_channel_setup(channelid)
	previous = {"category": setup["game_name"], "title": setup["title"], "tags": setup["tags"]}
	err = do_update(channelid, request.json)
	if err: return jsonify({"ok": False, "error": err})
	resp = {"ok": True, "success": "Stream status updated.", "previous": previous}
	if "mature" in request.json:
		# CJA 20210716: Since we can't view or update the Mature flag for offline channels
		# via Helix, we query it via Kraken here.
		# 20220218: Still can't. So we can't check this any more.
		# is_mature = query("kraken/channels/" + channelid, token=None)["mature"]
		# if is_mature and not request.json["mature"]:
			# resp["mature"] = "NOTE: The channel is currently set to Mature, which may dissuade viewers."
		# elif not is_mature and request.json["mature"]:
			# resp["mature"] = "CAUTION: The channel is not currently set to Mature."
		resp["mature"] = "NOTE: As of 20220218, mature status must be manually checked."
	return jsonify(resp)

@app.route("/api/twitter_cfg", methods=["POST"])
@wants_channelid
def update_twitter_cfg(channelid):
	sched = request.json.get("stdsched", "custom")
	if not sched or sched == "custom":
		sched = request.json.get("custsched")
	try: sched = int(str(sched))
	except ValueError: return jsonify({"ok": False, "error": "Invalid schedule time"})
	# Potentially bounds-check and/or round? We return the processed number
	# in case it isn't the same as the input, even though currently it's
	# always the same value, intified.
	database.update_twitter_config(channelid, sched)
	return jsonify({"ok": True, "success": "Twitter defaults updated",
		"new_sched": sched})

def get_schedule(channelid, delta=0):
	cursor = ""
	schedule = []
	now = datetime.datetime.now().astimezone(datetime.timezone.utc) - datetime.timedelta(seconds=delta)
	nextweek = now + datetime.timedelta(days=7)
	while cursor is not None:
		try:
			data = query("helix/schedule", token="app", params={"broadcaster_id": channelid, "after": cursor}, auto_refresh=False)
		except requests.exceptions.HTTPError:
			data = { } # TODO: Only do this if we get specifically a 404
		if not data.get("data"): break
		segments = data["data"].get("segments")
		if not segments: break # Might not be an error - might just be that there aren't any
		for s in segments:
			tm = datetime.datetime.strptime(s["start_time"], "%Y-%m-%dT%H:%M:%S%z")
			if tm > nextweek: return schedule
			if s["canceled_until"]: continue
			if tm < now: continue # Event started in the past. Presumably it ends in the future.
			schedule.append({"title": s["title"], "category": s.get("category") or {},
				"start_time": s["start_time"], "unixtime": int(tm.timestamp()) + delta})
		cursor = data["pagination"].get("cursor")
	return schedule

@app.route("/api/twitch_schedule")
@wants_channelid
def fetch_schedule(channelid):
	if "twitch_user" not in session: return jsonify({"ok": False, "error": "Unauthorized"})
	return jsonify({"ok": True, "schedule": get_schedule(channelid)});

@app.route("/checklist", methods=["POST"])
@wants_channelid
def update_checklist(channelid):
	if "twitch_user" not in session:
		return redirect(url_for("mainpage"))
	database.set_checklist(channelid, request.form["checklist"].strip().replace("\r", ""))
	return redirect(url_for("mainpage"))

def do_tweet(channelid, tweet, schedule, auth):
	if not tweet: return "Can't send an empty tweet" # or an empty list of tweets, but that shouldn't happen
	if not auth: return "Need to authenticate with Twitter before sending tweets"
	if schedule == "now":
		info = send_tweet((auth["oauth_token"], auth["oauth_token_secret"]), tweet)
		return info.get("error", "")
	events = get_schedule(channelid, int(schedule))
	if not events: return "Can't schedule tweets without a schedule!"
	target = events[0]["unixtime"]
	if target - time.time() > 1800:
		# Protect against schedule mistakes and various forms of insanity
		# The half-hour limit aligns with the Heroku policy of shutting a
		# dyno down after 30 mins of inactivity, which means we guarantee
		# that this tweet will indeed happen prior to dyno sleep.
		# (Dyno sleep? Not the "Slumbering Dragon" from M13 methinks.)
		return "Refusing to schedule a tweet more than half an hour in advance"
	# TODO: Retain the tweet and token in Postgres in case the server restarts
	# We'll assume the token won't need changing - but we assume that already.
	# Keep the one-hour limit (give or take) to minimize the likelihood of the
	# token expiring. Don't fret the weirdnesses; if stuff breaks, be sure the
	# tweets get retained, and then let Twitter worry about deduplication - it
	# apparently isn't possible to post the same tweet twice. (Whodathunk?) So
	# if tweeting fails, check to see if it was "duplicate status", and if so,
	# remove the tweet from the database. (Otherwise, error means "try again",
	# unless we just want to schedule tweets as fire-and-forget.)
	scheduler.put(target, send_tweet, (auth["oauth_token"], auth["oauth_token_secret"]), tweet)
	return None

def send_tweet(auth, tweet, in_reply_to=None):
	"""Actually send a tweet"""
	if isinstance(tweet, list):
		# It's a thread of tweets
		prev = ret = None
		for part in tweet:
			if not part: continue
			info = send_tweet(auth, part, in_reply_to=prev)
			if "error" in info: return info
			if not ret: ret = info # Return the info for the *first* tweet sent
			prev = info["tweet_id"]
		return ret or {"error": "Can't send a thread of nothing but empty tweets"}
	twitter = OAuth1Session(config.TWITTER_CLIENT_ID, config.TWITTER_CLIENT_SECRET, auth[0], auth[1])
	resp = twitter.post("https://api.twitter.com/1.1/statuses/update.json",
		data={"status": tweet, "in_reply_to_status_id": in_reply_to})
	if resp.status_code != 200:
		print("Unknown response from Twitter")
		print(resp.status_code)
		print("---")
		print(resp.json())
		print("---")
		try:
			# TODO: Report these to the front end somehow even if asynchronous
			return {"error": "Unable to send tweet: " + resp.json()["errors"][0]["message"]}
		except LookupError:
			return {"error": "Unknown error response from Twitter (see server console)"}
	r = resp.json()
	url = "https://twitter.com/%s/status/%s" % (r["user"]["screen_name"], r["id_str"])
	return {"screen_name": r["user"]["screen_name"], "tweet_id": r["id"], "url": url}

@app.route("/tweet", methods=["POST"])
@wants_channelid
def form_tweet(channelid):
	err = do_tweet(channelid, request.form.get("tweet"),
		request.form.get("tweetschedule", "now"), session.get("twitter_oauth"))
	if err: return err, 400
	return redirect(url_for("mainpage"))

def get_user_tweets():
	auth = session["twitter_oauth"]
	return list_scheduled_tweets(auth["oauth_token"], auth["oauth_token_secret"])

@app.route("/api/tweet", methods=["POST"])
@wants_channelid
def api_tweet(channelid):
	when = request.json.get("tweetschedule", "now")
	err = do_tweet(channelid, request.json.get("tweet"),
		when, session.get("twitter_oauth"))
	if err: return jsonify({"ok": False, "error": err})
	return jsonify({"ok": True, "success": "Tweet sent." if when == "now" else "Tweet scheduled.",
		"new_tweets": get_user_tweets()})

@app.route("/deltweet/<int:id>") # Deprecated
def cancel_tweet(id):
	auth = session["twitter_oauth"]
	cred = (auth["oauth_token"], auth["oauth_token_secret"])
	for tm, i, args in scheduler.search(send_tweet):
		if args[0] == cred and id == i:
			scheduler.remove(id)
			return redirect(url_for("mainpage"))
	return "No such tweet to remove (might have already been sent)"

@app.route("/api/tweet/<int:id>", methods=["DELETE"])
def api_cancel_tweet(id):
	auth = session["twitter_oauth"]
	cred = (auth["oauth_token"], auth["oauth_token_secret"])
	ret = {"ok": False, "error": "No such tweet to remove (might have already been sent)"}
	for tm, i, args in scheduler.search(send_tweet):
		if args[0] == cred and id == i:
			scheduler.remove(id)
			ret = {"ok": True, "success": "Tweet cancelled"}
			break
	ret["new_tweets"] = get_user_tweets()
	return jsonify(ret)

@app.route("/login")
def login():
	twitch = OAuth2Session(config.CLIENT_ID, config.CLIENT_SECRET,
		scope=REQUIRED_SCOPES)
	uri, state = twitch.create_authorization_url("https://id.twitch.tv/oauth2/authorize",
		redirect_uri=os.environ.get("OVERRIDE_REDIRECT_URI") or url_for("authorized", _external=True))
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
	user = query("helix/users", token="bearer")["data"][0]
	user["_id"] = user["id"] # For now, everything looks for _id. Existing logins don't have user["id"].
	database.create_user(user["_id"])
	session["twitch_user"] = user
	return redirect(url_for("mainpage"))

@app.route("/login-twitter")
def login_twitter():
	twitter = OAuth1Session(config.TWITTER_CLIENT_ID, config.TWITTER_CLIENT_SECRET,
		redirect_uri=url_for("authorized_twitter", _external=True))
	session["twitter_state"] = twitter.fetch_request_token("https://api.twitter.com/oauth/request_token")
	return redirect(twitter.create_authorization_url("https://api.twitter.com/oauth/authenticate"))

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
@wants_channelid
def create_timer(channelid):
	database.create_timer(channelid)
	return redirect(url_for("mainpage"))

@app.route("/timer/<id>")
def edit_timer(id):
	# NOTE: This doesn't get told what the channel ID is, it just does a perms check.
	# The channel ID will be carried through in the POST data though.
	info = database.get_timer_details(id)
	if not info or not may_edit_channel(session["twitch_user"]["_id"], info["twitchid"]):
		return "Timer not found, or not owned by you", 404
	return render_template("timer.html", info=info, channelid=info["twitchid"])

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

# Can also delete a timer
@app.route("/timer/<id>", methods=["POST"])
@wants_channelid
def save_timer(id, channelid):
	if "delete" in request.form: database.delete_timer(channelid, id)
	else: database.update_timer_details(channelid, id,
		title=request.form["title"],
		delta=parse_time(request.form["delta"]),
		maxtime=parse_time(request.form["maxtime"]),
		styling=request.form.get("styling", ""),
	)
	return redirect(url_for("mainpage"))

@app.route("/countdown/<id>")
def countdown(id):
	info = database.get_public_timer_details(id)
	if not info: return "Timer not found", 404
	events = get_schedule(info["twitchid"], int(info["delta"]))
	return render_template("countdown.html", id=id, **info, next_event=events[0]["unixtime"] if events else 0)

# ---- Live search API ----

@app.route("/search/game")
def findgame():
	if request.args["q"] == "": return jsonify([]) # Prevent failure in Twitch API call
	cats = query("helix/search/categories", params={"query": request.args["q"], "first": "50"}, token="bearer")
	return jsonify([{
		"name": cat["name"], "boxart": cat["box_art_url"], "id": cat["id"],
		# Compatibility shims for cached clients (20200619)
		"localized_name": cat["name"], "box": {"small": cat["box_art_url"]},
	} for cat in cats["data"] or ()])

@app.route("/search/tag")
def findtag():
	return jsonify(database.find_tags_by_prefix(request.args["q"]))

# ---- Config management API ----

@app.route("/api/hello")
def helloworld():
	info = {"user": None, "version": sys.version}
	if "twitch_user" in session:
		info["user"] = session["twitch_user"]["display_name"]
	return jsonify(info)

@app.route("/api/setups")
@wants_channelid
def list_setups(channelid):
	return jsonify(database.list_setups(channelid))

@app.route("/api/setups", methods=["POST"])
@wants_channelid
def create_setup(channelid):
	if not request.json: return jsonify({}), 400
	missing = {"category", "title"} - set(request.json)
	if missing:
		return jsonify({"error": "Missing: " + ", ".join(sorted(missing))}), 400
	setup = database.create_setup(channelid, **request.json)
	return jsonify(setup)

@app.route("/api/setups/<int:setupid>", methods=["DELETE"])
@wants_channelid
def delete_setup(channelid, setupid):
	deleted = database.delete_setup(channelid, setupid)
	if deleted: return "", 204
	return "", 404

@app.route("/mustard-backup.json")
@wants_channelid
def make_backup(channelid):
	twitchid = channelid
	response = "{\n"
	# Setups
	setups = database.list_setups(twitchid)
	response += '\t"setups": [\n'
	fields = "category", "title", "tags", "mature", "tweet"
	for setup in setups:
		setup = {field: setup[field] for field in fields}
		response += "\t\t" + json.dumps(setup) + ",\n"
	response += '\t\t""\n\t],\n'
	# Twitter config (formerly Schedule)
	[sched_tweet] = database.get_twitter_config(twitchid)
	response += '\t"twitter_config": [%d],\n' % sched_tweet
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
@wants_channelid
def restore_backup(channelid):
	twitchid = channelid
	if not twitchid:
		return redirect(url_for("mainpage"))
	try:
		data = json.loads(request.files["backup"].read().decode("utf-8"))
	except (KeyError, UnicodeDecodeError, json.JSONDecodeError):
		return "Backup file unreadable - must be a JSON file saved from Mustard Mine.", 400
	# Signature (from footer)
	if data[""] != "Mustard-Mine Backup":
		return "Backup file corrupt - signature missing.", 400
	r = database.restore_from_json(twitchid, data)
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
		except json.JSONDecodeError: continue
		if type(message) is not dict: continue # Again, very strict
		if "type" not in message: continue
		# Okay, we have a properly-formed message.
		if message["type"] == "init":
			if timerid: continue # Don't initialize twice
			if "id" not in message or not message["id"]: continue
			timerid = message["id"]
			timer_sockets[timerid].append(ws)
			ws.send(json.dumps({"type": "inited"}))
		if message["type"] == "logme":
			# Sometimes we're working in a context that has no logging
			# facilities available. Provide some very basic logging via
			# the server's console. Strictly strings only, and shortish.
			msg = message.get("msg")
			if type(msg) is str and len(msg) < 1000:
				print("Log message from socket: %r" % msg)
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
@wants_channelid
def adjust_all_timers(channelid, delta, negative=False):
	if negative: delta = -delta # Since the int converter can't handle negatives, we do them manually.
	if not channelid: return redirect(url_for("mainpage"))
	for id, timer in database.list_timers(channelid):
		if id in timer_sockets:
			for ws in timer_sockets[id]:
				ws.send(json.dumps({"type": "adjust", "delta": delta}))
	return "", 204

@app.route("/timer-force-all/<int:tm>")
@wants_channelid
def force_all_timers(channelid, tm):
	if not channelid: return redirect(url_for("mainpage"))
	for id, timer in database.list_timers(channelid):
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
