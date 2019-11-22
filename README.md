Mustard-Mine - Twitch Go-Live assistant
=======================================

    The more work there is of mine, the less there is of yours.
    -- The Duchess (attrib)

Source code for https://mustard-mine.herokuapp.com/ and also available for
individual deployment as desired.

TODO:

* Connect to Discord? cf Arghded
  - Have registered bot account MustardMine#2353
  - Configuration:
    - Needs "identify webhook.incoming" OAuth scopes
    - Upon authorization, will return a webhook ID and token, and the guild and channel IDs
    - GET /guilds/{guild.id}
    - GET /channels/{channel.id}
    - Build a "descriptor" from the guild name and channel name
    - Shouldn't need the guild/channel IDs after that unless it's worth updating the names
    - POST to the webhook
      - https://discordapp.com/developers/docs/resources/webhook#execute-webhook
    - Each channel to be posted to will require separate authorization.
    - See discord-integration branch for partial implementation.
* Query StreamLabs extension for schedule?
  - Would require assistance from SL, which they don't currently offer
  - Reverse-engineering is impractical; needs an API.
* Create one database transaction per incoming HTTP request, for efficiency
  - Currently all operations that *require* atomicity are done with single
    calls to database.py (and single transactions within that), but the
    landing page has a ton of separate (read-only) queries.
* Work on styling... lots.
* Support chat integrations? Have reserved the Twitch username MustardMine
  for this purpose.
  - Maybe after sending a scheduled tweet, format a message for chat with
    the link? Could be handy for a few channels.
    - The link itself is available inside send_tweet() but isn't currently
      used anywhere.
    - Could become another of the defaults in the twitter_cfg dialog.
* Get someone on a Mac to test things in Safari
  - The <dialog> tag isn't officially supported. Is my monkeypatch enough?
  - What should the Twitter MLE react to for "send now"? Ctrl-Enter okay?
* Can it be made so mods can be given permission to select a pre-built
  setup? Editors get full access (including seeing MM's own configs).
  - Also, editors probably shouldn't get any of the tweeting info. They
    can't actually send or manage the tweets (that's based on Twitter
    OAuth), so it's only going to be confusing to let them see the forms.
    This implies the need for two, and potentially three, permission-based
    views - owner, editor, maybe moderator. (What if the editor is the one
    who has control of the Twitter account though??)
* Maybe make a "copy setup to clipboard" to allow them to be shared? Use
  the same JSON format as is in the backup file, so you can cherry-pick
  from there too.


Requires Python 3.6 or newer. MAY run on 3.5 but not guaranteed.

NOTE: On Python 3.8+, newer versions of gevent and werkzeug may be needed:
pip install -v git+git://github.com/gevent/gevent.git#egg=gevent
pip install -v git+git://github.com/pallets/werkzeug
