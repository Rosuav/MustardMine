Mustard-Mine - Twitch Go-Live assistant
=======================================

    The more work there is of mine, the less there is of yours.
    -- The Duchess (attrib)

TODO:

* Refresh Twitch auth
* Connect to Twitter and send a tweet as you go live
  - Can currently do manually; needs to be linked to schedule
* Connect to Discord?
* Query StreamLabs extension for schedule??
  - Would require assistance from SL, which they don't currently offer
  - Reverse-engineering is impractical; needs an API.
* Allow a user to back up his/her saved setups as a JSON file
  - Format the file nicely - see ~/shed/steamguard for ideas
  - File should be 100% stable. Backing up twice with no changes
    should result in identical files.
  - File should be plain text and easy to diff.
  - Backup should be easy to take, but MUST require authentication
  - TODO: Include all important info. As features are added, ensure
    that they are backed up.
* Allow a user to restore saved setups from JSON backup
  - Naive: delete all and recreate
  - Smart: detect changes
* Custom check-list - saved list of items that get shown with tickboxes
* Simple HTML page containing a countdown timer
  - By default, it counts down to actual stream time
  - Can save an "offset time" that it'll count down to (eg "T +5 minutes")
  - Can manually alter the time
  - This page should be accessible w/o auth, and would be used for OBS
  - Allow custom CSS?
* Internal refactoring: use https://github.com/lepture/authlib
* Bug: Selecting a setup with fewer than 3 communities doesn't blank the spares
* Create one database transaction per incoming HTTP request, for efficiency
  - Currently all operations that *require* atomicity are done with single
    calls to database.py, but the landing page has a ton of separate queries.
