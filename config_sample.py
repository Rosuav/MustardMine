# Copy this file to config.py and edit it (not this file!) to have all your
# secrets and such. Obtain credentials from https://dev.twitch.tv/
CLIENT_ID = "..."
CLIENT_SECRET = "..."

# Obtain real credentials from https://apps.twitter.com
# These are a Twitter OAuth demo from Flask - okay for POC but not for live
# You'll need to create your application and use your own keys.
# This is the Flask-OAuth Example, but apparently Twitter don't mind if you change
# the callback URL. Not even "anything localhost is valid", which would be a great
# test account setup but still safe against abuse. No, absolutely ANYTHING will be
# accepted, and Twitter will redirect the user back to whatever you ask for.
TWITTER_CLIENT_ID = "xBeXxg9lyElUgwZT6AZ0"
TWITTER_CLIENT_SECRET = "aawnSpNTOVuDCjx7HMh6uSXetjNN8zWLpZwCEU4LBrk"

SESSION_SECRET = "..."
# import os, base64; SESSION_SECRET = base64.b64encode(os.urandom(12))

# PostgreSQL connection credentials
DATABASE_URI = "postgresql://localhost/"
