from flask import Flask, redirect, session, jsonify, url_for
from flask_oauthlib.client import OAuth
import requests

import config # ImportError? See config_sample.py
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
                          request_token_params={'scope': ["user_read"]}
)

@app.route("/")
def mainpage():
	if "twitch_token" in session:
		token = session["twitch_token"]
		r = requests.get("https://api.twitch.tv/kraken/user", headers={
			"Accept": "application/vnd.twitchtv.v5+json",
			"Client-ID": config.CLIENT_ID,
			"Authorization": "OAuth " + token,
		})
		user = r.json()
		return f"""<p>Welcome, {user["display_name"]}!</p><p><a href="/logout">Logout</a></p>"""
	return """<a href="/login"><img src="http://ttv-api.s3.amazonaws.com/assets/connect_dark.png" alt="Connect with Twitch"></a>"""

@twitch.tokengetter
def get_twitch_token(token=None):
	return session.get("twitch_token")

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

@app.route('/logout')
def logout():
	del session["twitch_token"]
	return redirect(url_for("mainpage"))

if __name__ == "__main__":
	import logging
	logging.basicConfig(level=logging.DEBUG)
	app.run(host='0.0.0.0')
