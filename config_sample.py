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

# Set this to an empty string to randomize every startup. This is secure
# against most forms of session secret leakage, but means that any time the
# server restarts, all sessions will be destroyed (meaning that all users get
# logged out). A constant string is far easier, but must be kept secret.
SESSION_SECRET = "..."

# PostgreSQL connection credentials
DATABASE_URI = "postgresql://localhost/"
