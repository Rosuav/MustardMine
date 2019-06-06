Mustard-Mine - Twitch Go-Live assistant
=======================================

    The more work there is of mine, the less there is of yours.
    -- The Duchess (attrib)

Source code for https://mustard-mine.herokuapp.com/ and also available for
individual deployment as desired.

TODO:

* Connect to Discord?
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
* Get someone on a Mac to test things in Safari
  - The <dialog> tag isn't officially supported. Is my monkeypatch enough?
  - What should the Twitter MLE react to for "send now"? Ctrl-Enter okay?
* Can it be made so mods can be given permission to update stuff? Maybe just
  selecting a pre-built setup?
* Prepopulate new accounts with some examples, including several in the same
  category, to show how this would be useful
* Need feedback on update/tweet now that it's all AJAXy


Requires Python 3.6 or newer. MAY run on 3.5 but not guaranteed.

NOTE: On Python 3.7+, gunicorn version 19.9.0 or newer is required, to
avoid a keyword collision on gunicorn.workers.async (renamed in 19.9).

NOTE: On Python 3.8, gevent may not build unless the version is labelled
3.8.0b1 or newer. Also, newer versions of gevent and werkzeug may be needed:
pip install -v git+git://github.com/gevent/gevent.git#egg=gevent
pip install -v git+git://github.com/pallets/werkzeug
