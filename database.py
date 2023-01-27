import psycopg2.extras
import config
import contextlib
import collections
import json
import os
import base64
import pytz
from datetime import datetime, timedelta

# NOTE: We use one single connection per process, but every function in this module
# creates its own dedicated cursor. This means that these functions should be thread
# safe; psycopg2 has thread-safe connections but not thread-safe cursors.
assert psycopg2.threadsafety >= 2
postgres = psycopg2.connect(config.DATABASE_URI)

# Assumes that dict preserves insertion order (CPython 3.6+, other Python 3.7+, possible 3.5)
# Otherwise, tables might be created in the wrong order, breaking foreign key refs.
TABLES = {
	"status": [ # Singleton table
		"tags_updated timestamptz not null default '1970-1-1Z'", # No longer needed as of 20220127
	],
	"users": [
		"twitchid integer primary key",
		"sched_tweet integer not null default 0",
		"checklist text not null default ''",
	],
	"setups": [
		"id serial primary key",
		"twitchid integer not null references mustard.users",
		"category text not null default ''",
		"title text not null default ''",
		"tags text not null default ''", # Comma-separated
		"mature boolean not null default false",
		"tweet text not null default ''",
	],
	"timers": [
		"id text primary key",
		"twitchid integer not null references mustard.users",
		"title text not null default ''",
		"delta integer not null default 0",
		"maxtime integer not null default 3600", # If time to event exceeds this, shows "NOW"
		"styling text not null default ''", # CSS - set by eg color selection
	],
}

# https://postgrespro.com/list/thread-id/1544890
# Allow <<DEFAULT>> to be used as a value in an insert statement
class Default(object):
	def __conform__(self, proto):
		if proto is psycopg2.extensions.ISQLQuote: return self
	def getquoted(self): return "DEFAULT"
DEFAULT = Default()
del Default

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
				need = [c for c in want if c not in have] # Set operations but preserving order to
				xtra = [c for c in have if c not in want] # the greatest extent possible.
				if not need and not xtra: continue # All's well!
				actions = ["add " + want[c] for c in need] + ["drop column " + c for c in xtra]
				cur.execute("alter table mustard." + table + " " + ", ".join(actions))
		cur.execute("select * from mustard.status")
		if cur.fetchone() is None:
			cur.execute("insert into mustard.status default values")
create_tables()

def create_user(twitchid): # Really "ensure_user" as it's quite happy to not-create if exists
	# TODO: Save the user's OAuth info, incl Twitter.
	try:
		with postgres, postgres.cursor() as cur:
			cur.execute("insert into mustard.users values (%s)", [twitchid])
		# As a separate transaction (it's okay if this fails), load up
		# the template data to give some samples.
		with open("template.json") as f:
			data = json.load(f)
		restore_from_json(twitchid, data)
	except psycopg2.IntegrityError:
		pass # TODO: Update any extra info eg Twitter OAuth

def create_setup(twitchid, *, category, title, tags="", mature=False, tweet="", **extra):
	"""Create a new 'setup' - a loadable stream config

	Returns the full record just created, including its ID.
	"""
	with postgres, postgres.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
		cur.execute("insert into mustard.setups (twitchid, category, title, tags, mature, tweet) values (%s, %s, %s, %s, %s, %s) returning *",
			(twitchid, category, title, tags, mature, tweet))
		ret = cur.fetchone()
	return ret

def list_setups(twitchid):
	with postgres, postgres.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
		cur.execute("select * from mustard.setups where twitchid=%s order by id", (twitchid,))
		ret = cur.fetchall()
	return ret

def delete_setup(twitchid, setupid):
	"""Attempt to delete a saved setup

	If the setupid is bad, or if it doesn't belong to the given twitchid,
	returns 0. There is no permissions-error response - just a 404ish.
	"""
	with postgres, postgres.cursor() as cur:
		cur.execute("delete from mustard.setups where twitchid=%s and id=%s", (twitchid, setupid))
		return cur.rowcount

def get_twitter_config(twitchid):
	"""Return the user's tweet schedule"""
	with postgres, postgres.cursor() as cur:
		cur.execute("select sched_tweet from mustard.users where twitchid=%s", (twitchid,))
		return cur.fetchone()

def update_twitter_config(twitchid, schedule):
	with postgres, postgres.cursor() as cur:
		cur.execute("update mustard.users set sched_tweet=%s where twitchid=%s",
			(schedule, twitchid))

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

def list_timers(twitchid, *, full=False):
	"""List the user's timers

	Returns their unique IDs, which are URL-safe strings, and titles, which
	usually aren't. If full is True, also returns additional fields.
	"""
	with postgres, postgres.cursor() as cur:
		morefields = ", delta, maxtime, styling" if full else ""
		cur.execute("select id, title" + morefields + " from mustard.timers where twitchid=%s order by id", (twitchid,))
		return cur.fetchall()

def get_timer_details(id):
	"""Get details for a specific timer

	Does not do a permissions check - will return data for ANY user's timers.
	Perms must be checked externally.
	"""
	with postgres, postgres.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
		cur.execute("select * from mustard.timers where id=%s", (id,))
		return cur.fetchone()

def get_public_timer_details(id):
	"""Get public details for a specific timer

	Requires no Twitch ID, but is guaranteed to return ONLY public info.
	"""
	with postgres, postgres.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
		cur.execute("select twitchid, title, delta, maxtime, styling from mustard.timers where id=%s", (id,))
		info = cur.fetchone()
		return info

def generate_timer_id():
	"""Generate an alphanumeric random identifier.

	Always returns a URL-safe and DB-safe value. If it would have used the
	last two characters in the base-64 alphabet, replace them with letters;
	this means we can potentially get collisions, but that's possible even
	without that hack, and this is the easiest way to make clean IDs.
	"""
	return base64.b64encode(os.urandom(30), b"Qx").decode("ascii")

def create_timer(twitchid):
	"""Create a new timer and return its unique ID"""
	# TODO: If we happen to collide, rerandomize instead of failing
	with postgres, postgres.cursor() as cur:
		id = generate_timer_id()
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

def delete_timer(twitchid, id):
	"""Delete a timer, but only if it's owned by that twitchid

	Raises ValueError if it found nothing to delete
	"""
	with postgres, postgres.cursor() as cur:
		cur.execute("delete from mustard.timers where id=%s and twitchid=%s",
			(id, twitchid))
		if not cur.rowcount: raise ValueError("Timer not found, or not owned by that user")

class ValidationError(Exception): pass
class Restorer(contextlib.ExitStack):
	"""Context manager for a one-transaction full restoration action"""
	def __init__(self, twitchid):
		super().__init__()
		self.twitchid = twitchid
		self.summary = ""

	def __enter__(self):
		super().__enter__()
		self.enter_context(postgres)
		self.cur = self.enter_context(postgres.cursor())
		# List all pre-existing timers so untouched ones can get wiped
		self.cur.execute("select id from mustard.timers where twitchid=%s", (self.twitchid,))
		self.timers = {tm[0] for tm in self.cur}
		return self

	def __exit__(self, t, v, tb):
		super().__exit__(t, v, tb)
		print("__exit__: t is", t)
		if t is not None:
			self.failed = True
			if t is ValidationError:
				print("Returning true")
				self.summary += "--> " + v.args[0] + "\n"
				return True
			self.summary = "" # TODO: Summarize the failure?
		else:
			self.failed = False

	def fail(self, msg="Malformed backup file"):
		"""Abort the restoration with a message. Uses exception handling to unwind everything."""
		raise ValidationError(msg)

	def check_dict(self, data):
		if not isinstance(data, dict): raise ValidationError("Invalid data format")
		if "self" in data: raise ValidationError("Invalid key in data") # I doubt anyone will see this, but keep us safe

	def wipe_setups(self):
		self.cur.execute("delete from mustard.setups where twitchid = %s", (self.twitchid,))

	def restore_setup(self, *, category=None, title=None, tags="", mature=False, tweet=""):
		if not category or not title: raise ValidationError("Setups: Category and title are required")
		self.cur.execute("insert into mustard.setups (twitchid, category, title, tags, mature, tweet) values (%s, %s, %s, %s, %s, %s) returning id",
			(self.twitchid, category, title, tags, mature, tweet))
		self.summary += "Restored %r setup\n" % category

	def restore_twitter_config(self, tweet):
		self.cur.execute("update mustard.users set sched_tweet=%s where twitchid=%s",
			(tweet, self.twitchid))
		self.summary += "Restored default tweet schedule\n"

	def restore_checklist(self, checklist):
		self.cur.execute("update mustard.users set checklist=%s where twitchid=%s", (checklist, self.twitchid,))
		self.summary += "Restored personal checklist\n"

	def restore_timer(self, *, id, title=None, delta=None, maxtime=None, styling=None):
		if id in self.timers:
			# It existed already. Update it.
			self.timers.remove(id)
			self.cur.execute("""update mustard.timers set
						title=coalesce(%s, title), delta=coalesce(%s, delta),
						maxtime=coalesce(%s, maxtime), styling=coalesce(%s, styling)
					where id=%s""",
				(title, delta, maxtime, styling, id))
			self.summary += "Restored details for timer %s\n" % id
		else:
			# It didn't exist, or you tried to restore two timers with the same ID.
			# Generate a new ID and create a brand new timer. Note that if you mess
			# up the ID, it'll be ignored and a new one created, and then the old
			# will get destroyed. So repeatedly restoring a file with the wrong ID
			# in it will churn your IDs, but nothing else (you won't accrue timers).
			id = generate_timer_id(); twitchid = self.twitchid
			args = [DEFAULT if x is None else x for x in (id, twitchid, title, delta, maxtime, styling)]
			self.cur.execute("insert into mustard.timers (id, twitchid, title, delta, maxtime, styling) values (%s, %s, %s, %s, %s, %s)", args)
			self.summary += "Recreated timer %s\n" % id

	def wipe_untouched_timers(self):
		# Delete any timer that wasn't restored
		for id in self.timers:
			self.cur.execute("delete from mustard.timers where id=%s", (id,))
			self.summary += "Deleted timer %s\n" % id

def restore_from_json(twitchid, data):
	# Open a single database transaction and do all the work.
	with Restorer(twitchid) as r:
		if "setups" in data:
			r.wipe_setups()
			for setup in data["setups"]:
				if setup == "": continue # The shim at the end
				if "communities" in setup:
					# Previously, Twitch had "communities", which no longer do anything.
					# Silently remove them from the data.
					del setup["communities"]
				r.check_dict(setup)
				r.restore_setup(**setup)
		if "schedule" in data: # Deprecated in favour of "twitter_config"
			sched = data["schedule"]
			if not isinstance(sched, list): r.fail()
			elif len(sched) == 8: r.restore_twitter_config(0)
			elif len(sched) == 9: r.restore_twitter_config(int(sched[-1]))
			else: r.fail()
		if "twitter_config" in data:
			cfg = data["twitter_config"]
			if not isinstance(cfg, list) or not cfg: r.fail()
			else: r.restore_twitter_config(int(cfg[0]))
		if "checklist" in data:
			checklist = data["checklist"]
			if isinstance(checklist, list): checklist = "\n".join(checklist).strip()
			if not isinstance(checklist, str): r.fail()
			r.restore_checklist(checklist)
		if "timers" in data:
			# This one is problematic. We can't simply wipe and recreate because IDs
			# are significant (they're the external references, so people's OBS configs
			# will have those same IDs in them).
			for timer in data["timers"]:
				if timer == "": continue # The shim
				r.check_dict(timer)
				r.restore_timer(**timer)
			r.wipe_untouched_timers()
	return r
