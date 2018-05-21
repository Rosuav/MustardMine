# Copy this file to config.py and edit it (not this file!) to have all your
# secrets and such. Alternatively, create environment variables with all of
# these names, and ensure that config.py does not exist (as config.py takes
# precedence over the environment).

# Obtain credentials from https://dev.twitch.tv/
CLIENT_ID = "..."
CLIENT_SECRET = "..."

# Obtain credentials from https://apps.twitter.com/
TWITTER_CLIENT_ID = "..."
TWITTER_CLIENT_SECRET = "..."

SESSION_SECRET = "..."
# import os, base64; SESSION_SECRET = base64.b64encode(os.urandom(12))

# PostgreSQL connection credentials
DATABASE_URI = "postgresql://localhost/"
