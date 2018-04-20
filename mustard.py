from flask import Flask, render_template, g, Markup, request, redirect
from flask_oauthlib.client import OAuth

import config # ImportError? See config_sample.py
app = Flask(__name__)

twitch = OAuth().remote_app('twitch',
                          base_url='https://api.twitch.tv/kraken/',
                          request_token_url=None,
                          access_token_method='POST',
                          access_token_url='https://api.twitch.tv/kraken/oauth2/token',
                          authorize_url='https://api.twitch.tv/kraken/oauth2/authorize',
                          consumer_key=config.CLIENT_ID,
                          consumer_secret=config.CLIENT_SECRET,
                          request_token_params={'scope': ["user_read", "channel_check_subscription"]}
                          )

@app.route("/")
def mainpage():
	return "Hello, world!"

if __name__ == "__main__":
	import logging
	logging.basicConfig(level=logging.DEBUG)
	app.run(host='0.0.0.0')
