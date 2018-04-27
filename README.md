Mustard-Mine - Twitch Go-Live assistant
=======================================

    The more work there is of mine, the less there is of yours.
    -- The Duchess (attrib)

TODO:

* Connect to Twitter and send a tweet as you go live
* Connect to Discord?
* Negotiate with StreamLabs extension for schedule??
  - Which direction? Configure SL or query it?
* Allow a user to back up his/her saved setups as a JSON file
  - Format the file nicely - see ~/shed/steamguard for ideas
  - File should be 100% stable. Backing up twice with no changes
    should result in identical files.
  - File should be plain text and easy to diff.
  - Backup should be easy to take, but MUST require authentication
* Allow a user to restore saved setups from JSON backup
  - Naive: delete all and recreate
  - Smart: detect changes
