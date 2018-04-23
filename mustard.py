import json
from pprint import pprint
from flask import Flask, request, redirect, session, jsonify, url_for
from flask_oauthlib.client import OAuth
import requests

import config # ImportError? See config_sample.py
app = Flask(__name__)
app.secret_key = config.SESSION_SECRET

# Map community names to their IDs
# If a name is not present, look up the ID and cache it here.
community_id = {}

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
	# TODO eventually: Create an application and use our own keys, stored on config.py
	# This is the Flask-OAuth Example, but apparently Twitter don't mind if you change
	# the callback URL. Not even "anything localhost is valid", which would be a great
	# test account setup but still safe against abuse. No, absolutely ANYTHING will be
	# accepted, and Twitter will redirect the user back to whatever you ask for.
	consumer_key='xBeXxg9lyElUgwZT6AZ0A',
	consumer_secret='aawnSpNTOVuDCjx7HMh6uSXetjNN8zWLpZwCEU4LBrk',
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
		twitter = """<a href="/login-twitter"><img src="/static/Twitter_Social_Icon_Square_Color.svg" alt="Twitter logo" height=32>Connect with Twitter</a>"""
	if "twitch_token" in session:
		token = session["twitch_token"]
		user = query("user")
		session["twitch_user"] = user
		channel = query("channels/" + user["_id"])
		communities = query("channels/" + user["_id"] + "/communities")
		for community in communities["communities"]:
			community_id[community["name"]] = community["_id"]
		commnames = [comm["name"] for comm in communities["communities"]]
		return twitter + f"""<p>Welcome, {user["display_name"]}!</p>
		<form method=post action="/update">
		<ul>
		<li>Category: <input name=category size=50></li>
		<li>Stream title: <input name=title size=50></li>
		<li>Communities: <input name=comm1 size=50><br>
		<input name=comm2 size=50><br>
		<input name=comm3 size=50><br>
		</ul>
		<input type=submit>
		<script>
		const channel = {json.dumps(channel)};
		const communities = {json.dumps(commnames)};
		const form = document.forms[0].elements;
		form.category.value = channel.game;
		form.title.value = channel.status;
		communities.forEach((c, i) => form["comm"+(i+1)].value = c);
		</script>
		</form>
		<p><a href="/logout">Logout</a></p>"""
	return """<a href="/login"><img src="http://ttv-api.s3.amazonaws.com/assets/connect_dark.png" alt="Connect with Twitch"></a>""" + twitter

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
		if name not in community_id:
			resp = query("communities", params={"name": name})
			community_id[name] = resp["_id"]
		communities.append(community_id[name])
	print(communities)
	query("channels/" + user["_id"] + "/communities", method="PUT", data={
		"community_ids[]": communities,
	})
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
	del session["twitch_token"]
	del session["twitter_oauth"]
	return redirect(url_for("mainpage"))

if __name__ == "__main__":
	import logging
	logging.basicConfig(level=logging.INFO)
	app.run(host='0.0.0.0')
