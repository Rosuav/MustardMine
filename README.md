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
* Countdown timer:
  - Allow manual altering the time, Christine-style
  - Allow custom CSS? Currently stubbed out
* Internal refactoring: use https://github.com/lepture/authlib
* Create one database transaction per incoming HTTP request, for efficiency
  - Currently all operations that *require* atomicity are done with single
    calls to database.py (and single transactions within that), but the
    landing page has a ton of separate (read-only) queries.

Requires Python 3.6 or newer. MAY run on 3.5 but not guaranteed.
