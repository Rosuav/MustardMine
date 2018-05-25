import psycopg2.extras
import config
import collections
import os
import base64
import pytz
from datetime import datetime, timedelta

postgres = psycopg2.connect(config.DATABASE_URI)

# Assumes that dict preserves insertion order (CPython 3.6+, other Python 3.7+, possible 3.5)
# Otherwise, tables might be created in the wrong order, breaking foreign key refs.
TABLES = {
	"users": [
		"twitchid integer primary key",
		"sched_timezone varchar not null default ''",
		"schedule varchar not null default ''",
		"checklist text not null default ''",
	],
	"setups": [
		"id serial primary key",
		"twitchid integer not null references mustard.users",
		"category text not null default ''",
		"title text not null default ''",
		"tweet text not null default ''",
	],
	"communities": [
		"name text primary key",
		"twitchid text not null",
		"descr text not null default ''",
	],
	"setup_communities": [
		"setupid integer not null references mustard.setups on delete cascade",
		"community text not null references mustard.communities",
	],
	"timers": [
		"id text primary key",
		"twitchid integer not null references mustard.users",
		"title text not null default ''",
		"delta integer not null default 0",
		"maxtime integer not null default 3600", # If time to event exceeds this, shows "NOW"
		"styling text not null default ''", # custom CSS??
	],
}

def create_tables():
	with postgres, postgres.cursor() as cur:
		cur.execute("create schema if not exists mustard")
		cur.execute("""select table_name, column_name
				from information_schema.columns
				where table_schema = 'mustard'
				order by ordinal_position""")
		tables = collections.defaultdict(list)
		for table, column in cur:
			tables[table].append(column)
		for table, columns in TABLES.items():
			if table not in tables:
				# Table doesn't exist - create it. Yes, I'm using percent
				# interpolation, not parameterization. It's an unusual case.
				cur.execute("create table mustard.%s (%s)" % (
					table, ",".join(columns)))
			else:
				# Table exists. Check if all its columns do.
				# Note that we don't reorder columns. Removing works,
				# but inserting doesn't - new columns will be added at
				# the end of the table.
				want = {c.split()[0]: c for c in columns}
				have = tables[table]
				need = [c for c in want if c not in have]
				xtra = [c for c in have if c not in want]
				if not need and not xtra: continue # All's well!
				actions = ["add " + want[c] for c in need] + ["drop column " + c for c in xtra]
				cur.execute("alter table mustard." + table + " " + ", ".join(actions))
create_tables()

# Map community names to their IDs
# If a name is not present, look up the ID and cache it here.
_community_id = {}
def cache_community(community):
	"""Cache the info for a particular community.

	Saves both in memory and on disk. Assumes that it'll never change,
	which is a false assumption. This is one of the two hardest problems
	in computing, and I'm completely punting on it.
	"""
	_community_id[community["name"]] = community["_id"]
	args = (community["name"], community["summary"], community["_id"])
	with postgres, postgres.cursor() as cur:
		cur.execute("update mustard.communities set name=%s, descr=%s where twitchid=%s", args)
		if cur.rowcount: return
		cur.execute("insert into mustard.communities (name, descr, twitchid) values (%s, %s, %s)", args)

def get_community_id(name):
	return _community_id.get(name)

def create_user(twitchid):
	# TODO: Save the user's OAuth info, incl Twitter.
	try:
		with postgres, postgres.cursor() as cur:
			cur.execute("insert into mustard.users values (%s)", [twitchid])
	except psycopg2.IntegrityError:
		pass # TODO: Update any extra info eg Twitter OAuth

def create_setup(twitchid, category, title="", communities=(), tweet="", **extra):
	"""Create a new 'setup' - a loadable stream config

	Returns the full record just created, including its ID.
	The communities MUST have already been stored in the on-disk cache.
	"""
	with postgres, postgres.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
		cur.execute("insert into mustard.setups (twitchid, category, title, tweet) values (%s, %s, %s, %s) returning *",
			(twitchid, category, title, tweet))
		ret = cur.fetchone()
		id = ret["id"]
		# TODO: insertmany, but with individual error checking
		ret["communities"] = []
		for comm in communities:
			cur.execute("insert into mustard.setup_communities values (%s, %s)", (id, comm))
			ret["communities"].append(comm)
	return ret

def list_setups(twitchid):
	with postgres, postgres.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
		cur.execute("select * from mustard.setups where twitchid=%s order by id", (twitchid,))
		ret = cur.fetchall()
		for setup in ret:
			cur.execute("select community from mustard.setup_communities where setupid=%s", (setup["id"],))
			setup["communities"] = sorted([row["community"] for row in cur])
	return ret

def delete_setup(twitchid, setupid):
	"""Attempt to delete a saved setup

	If the setupid is bad, or if it doesn't belong to the given twitchid,
	returns 0. There is no permissions-error response - just a 404ish.
	"""
	with postgres, postgres.cursor() as cur:
		cur.execute("delete from mustard.setups where twitchid=%s and id=%s", (twitchid, setupid))
		return cur.rowcount

def get_schedule(twitchid):
	"""Return the user's timezone and schedule

	Schedule is split into seven (Sun through Sat) space-delimited strings.
	"""
	with postgres, postgres.cursor() as cur:
		cur.execute("select sched_timezone, schedule from mustard.users where twitchid=%s", (twitchid,))
		tz, sched = cur.fetchone()
		sched = sched.split(",") + [""] * 7
		return tz, sched[:7]

def set_schedule(twitchid, tz, schedule):
	with postgres, postgres.cursor() as cur:
		cur.execute("update mustard.users set sched_timezone=%s, schedule=%s where twitchid=%s", (tz, ",".join(schedule), twitchid))

def get_checklist(twitchid):
	"""Return the user's checklist

	Items are separated by \n in a single string.
	Empty string means no checklist.
	"""
	with postgres, postgres.cursor() as cur:
		cur.execute("select checklist from mustard.users where twitchid=%s", (twitchid,))
		return cur.fetchone()[0]

def set_checklist(twitchid, checklist):
	"""Update the checklist, which must be formatted as lines already"""
	with postgres, postgres.cursor() as cur:
		cur.execute("update mustard.users set checklist=%s where twitchid=%s", (checklist, twitchid,))

def list_timers(twitchid):
	"""List the user's timers

	Returns their unique IDs, which are URL-safe strings, and titles, which
	usually aren't.
	"""
	with postgres, postgres.cursor() as cur:
		cur.execute("select id, title from mustard.timers where twitchid=%s", (twitchid,))
		return cur.fetchall()

def get_timer_details(twitchid, id):
	"""Get details for a specific timer

	Will return data if the timer is owned by the given user, otherwise None.
	"""
	with postgres, postgres.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
		cur.execute("select * from mustard.timers where twitchid=%s and id=%s", (twitchid, id))
		return cur.fetchone()

def find_next_event(tz, sched, delta=0):
	if not sched.strip(","):
		# If you have no schedule set, there can't be any events.
		# Early check to prevent crashing out if no TZ set. If
		# you have a schedule but do *not* have a TZ, the below
		# code will bomb.
		return 0
	sched = sched.split(",") + [""] * 7
	sched = [[tm for tm in day.split(" ") if tm] for day in sched[:7]]
	tz = pytz.timezone(tz)
	now = datetime.now(tz=tz).replace(second=0, microsecond=0) - timedelta(seconds=delta)
	tm = (now.hour, now.minute)
	dow = now.isoweekday() % 7 # isoweekday returns 7 for Sunday, we want 0
	for tryme in range(8):
		for schedtime in sched[(dow + tryme) % 7]:
			hr, min = schedtime.split(":")
			# First pass, looking at today, we count only times in the future.
			# After that, we look at the first available time. If we go seven
			# full days into the future (weeklong wraparound), we take any
			# schedule entry from the current date.
			if tryme or tm < (int(hr), int(min)):
				# Advance to the right day
				target = now + timedelta(days=tryme)
				# Select the hour and minute, which might break stuff badly
				target = target.replace(hour=int(hr), minute=int(min))
				# Fix the timezone in case something's broken
				target = tz.normalize(target)
				# In case we went past a UTC offset change, re-replace.
				target = target.replace(hour=int(hr), minute=int(min))
				# In case we landed right inside a DST advancement, re-normalize.
				target = tz.normalize(target)
				# Convert to Unix time and return it!
				return int(target.timestamp())
	# Nothing? Strange. We were supposed to catch empty schedules up above.
	# Maybe there's a malformed entry that got skipped. In any case, this
	# is an empty schedule, so return failure.
	return 0

def get_public_timer_details(id):
	"""Get public details for a specific timer

	Requires no Twitch ID, but is guaranteed to return ONLY public info.
	In addition to the raw info, this also gives the UTC time of the next
	scheduled event.
	"""
	with postgres, postgres.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
		cur.execute("select twitchid, title, delta, maxtime, styling from mustard.timers where id=%s", (id,))
		info = cur.fetchone()
		if not info: return None
		twitchid = info.pop("twitchid")
		cur.execute("select sched_timezone, schedule from mustard.users where twitchid=%s", (twitchid,))
		sched = cur.fetchone()
		info["next_event"] = find_next_event(sched["sched_timezone"], sched["schedule"], info["delta"])
		return info

def get_next_event(twitchid, delta=0):
	"""Get the next event from this user's schedule

	Similar to get_public_timer_details but can provide arbitrary times
	and deltas, without requiring preconfigured timers. Returns the Unix
	time for the next event, or 0 if no events on this user's calendar.
	"""
	with postgres, postgres.cursor() as cur:
		cur.execute("select sched_timezone, schedule from mustard.users where twitchid=%s", (twitchid,))
		tz, sched = cur.fetchone()
		return find_next_event(tz, sched, delta)

def create_timer(twitchid):
	"""Create a new timer and return its unique ID"""
	# TODO: If we happen to collide, rerandomize instead of failing
	with postgres, postgres.cursor() as cur:
		# Generate an alphanumeric random identifier. If it would have used the
		# last two characters in the base-64 alphabet, replace them with letters;
		# this means we can potentially get collisions, but that's possible even
		# without that hack, and this is the easiest way to make clean IDs.
		id = base64.b64encode(os.urandom(30), b"Qx").decode("ascii")
		cur.execute("insert into mustard.timers (id, twitchid) values (%s, %s)", (id, twitchid))
		return id

def update_timer_details(twitchid, id, *, title, delta, maxtime, styling):
	"""Update a timer, but only if it's owned by that twitchid

	Raises ValueError if it found nothing to update
	"""
	with postgres, postgres.cursor() as cur:
		
		cur.execute("update mustard.timers set title=%s, delta=%s, maxtime=%s, styling=%s where id=%s and twitchid=%s",
			(title, delta, maxtime, styling, id, twitchid))
		if not cur.rowcount: raise ValueError("Timer not found, or not owned by that user")
