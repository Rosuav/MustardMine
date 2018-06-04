Mustard-Mine - Twitch Go-Live assistant
=======================================

    The more work there is of mine, the less there is of yours.
    -- The Duchess (attrib)

Source code for https://mustard-mine.herokuapp.com/ and also available for
individual deployment as desired.

TODO:

* Connect to Discord?
* Query StreamLabs extension for schedule??
  - Would require assistance from SL, which they don't currently offer
  - Reverse-engineering is impractical; needs an API.
* Create one database transaction per incoming HTTP request, for efficiency
  - Currently all operations that *require* atomicity are done with single
    calls to database.py (and single transactions within that), but the
    landing page has a ton of separate (read-only) queries.

Requires Python 3.6 or newer. MAY run on 3.5 but not guaranteed.

CAUTION: On Python 3.7+, gunicorn.workers.async collides with the keyword.
This may need to be hacked, until such time as a new release of gunicorn
fixes this. (Last checked 20180528; there's a GitHub issue from a few days
ago which should resolve this.)
