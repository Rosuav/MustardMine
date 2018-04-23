import json
from pprint import pprint
from flask import Flask, request, redirect, session, url_for, g, render_template
from flask_oauthlib.client import OAuth
import requests

import config # ImportError? See config_sample.py
import database
app = Flask(__name__)
app.secret_key = config.SESSION_SECRET

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

def query(endpoint, *, token=None, method="GET", params=None, data=None):
	if token is None:
		token = session["twitch_token"]
	r = requests.request(method, "https://api.twitch.tv/kraken/" + endpoint,
		params=params, data=data, headers={
		"Accept": "application/vnd.twitchtv.v5+json",
		"Client-ID": config.CLIENT_ID,
		"Authorization": "OAuth " + token,
	})
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
	return render_template("index.html",
		twitter=twitter, username=user["display_name"],
		channel=json.dumps(channel), commnames=json.dumps(commnames),
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
	print(communities)
	query("channels/" + user["_id"] + "/communities", method="PUT", data={
		"community_ids[]": communities,
	})
	return redirect(url_for("mainpage"))

@app.route("/tweet", methods=["POST"])
def tweet():
	tweet = request.form.get("tweet")
	if not tweet or "twitter_oauth" not in session:
		return redirect(url_for("mainpage"))
	g.user = session["twitter_oauth"]
	resp = twitter.post("statuses/update.json", data={"status": tweet})
	print(resp.status)
	print(resp.data)
	# TODO: 403 means too long, so report on that
	return redirect(url_for("mainpage"))

@app.route("/login")
def login():
	return twitch.authorize(callback=url_for("authorized", _external=True))

@app.route("/login/authorized")
def authorized():
	resp = twitch.authorized_response()
	if resp is None:
		return "Access denied: reason=%s error=%s" % (
			request.args['error'],
			request.args['error_description']
		)
	session["twitch_token"] = resp["access_token"]
	user = query("user")
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

if __name__ == "__main__":
	import logging
	logging.basicConfig(level=logging.INFO)
	app.run(host='0.0.0.0')
