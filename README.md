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
* Create one database transaction per incoming HTTP request, for efficiency
  - Currently all operations that *require* atomicity are done with single
    calls to database.py (and single transactions within that), but the
    landing page has a ton of separate (read-only) queries.
* Work on styling... lots.
* Support chat integrations? Have reserved the Twitch username MustardMine
  for this purpose.
  - Maybe after sending a scheduled tweet, format a message for chat with
    the link? Could be handy for a few channels.
    - The link itself is part of send_tweet()'s return value, fwiw.
    - Could become another of the defaults in the twitter_cfg dialog.
  - This would also be a good way to report tweet errors to the broadcaster.
    Though I'm not expecting any, there's always the possibility that some
    desync or bug will result in a back-end error.
* Get someone on a Mac to test things in Safari
  - The <dialog> tag is officially supported only from v15.4 onwards, and
    older versions are still in use. Is my monkeypatch enough?
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
* Tags are currently restricted to old-style (limit 5, use the IDs). When
  the Twitch API grows support for new-style tags (limit 10, free-form),
  switch to pushing those out. Saved setups may need to be migrated, eg
  "Family Friendly" to "FamilyFriendly", but hopefully Twitch will return
  them in the correct format.


Requires Python 3.6 or newer. MAY run on 3.5 but not guaranteed.

NOTE: On Python 3.8+, newer versions of gevent and werkzeug may be needed:
pip install -v git+git://github.com/gevent/gevent.git#egg=gevent
pip install -v git+git://github.com/pallets/werkzeug


Hosting options
---------------

Heroku is removing its free tier. Eventually, it will not be possible to host
Mustard Mine on Heroku without paying money. Where can we mine this valuable
mineral as inexpensively as possible?

* Heroku - Hobby dyno $7 + Hobby Basic database $9 = $16/mo
  https://www.heroku.com/pricing
* NodeChef - the absolute minimum should be fine, $7 container + $2 database
  https://www.nodechef.com/pricing
* Qovery - free tier maybe? Awaiting signup response for more details.
  https://www.qovery.com/pricing/
* PythonAnywhere - no PGSQL on free tier, not even external. Custom minimum
  $5 for CPU and $7 for DB = $12/mo.
  https://www.pythonanywhere.com/pricing/
  ElephantSQL may be an option here, still requires paid app hosting but the
  DB would be $0. https://www.elephantsql.com/plans.html
* DigitalOcean droplet $4/mo but I'd have to do all the mgt
  https://www.digitalocean.com/pricing
