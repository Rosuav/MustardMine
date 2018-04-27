import psycopg2.extras
import config

postgres = psycopg2.connect(config.DATABASE_URI)

CREATE_TABLE = (
	"""create schema if not exists mustard""",
	"""create table if not exists mustard.users (
		twitchid integer primary key
	)""",
	"""create table if not exists mustard.setups (
		id serial primary key,
		twitchid integer not null references mustard.users,
		category text not null default '',
		title text not null default ''
	)""",
	"""create table if not exists mustard.communities (
		name text primary key,
		twitchid text not null,
		descr text not null default ''
	)""",
	"""create table if not exists mustard.setup_communities (
		setupid integer not null references mustard.setups on delete cascade,
		community text not null references mustard.communities
	)""",
)

def create_tables():
	with postgres, postgres.cursor() as cur:
		for tb in CREATE_TABLE:
			cur.execute(tb)
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

def create_setup(twitchid, category, title="", communities=(), **extra):
	"""Create a new 'setup' - a loadable stream config

	Returns the full record just created, including its ID.
	The communities MUST have already been stored in the on-disk cache.
	"""
	with postgres, postgres.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
		cur.execute("insert into mustard.setups (twitchid, category, title) values (%s, %s, %s) returning *",
			(twitchid, category, title))
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
		cur.execute("select * from mustard.setups where twitchid=%s", (twitchid,))
		ret = cur.fetchall()
		for setup in ret:
			cur.execute("select community from mustard.setup_communities where setupid=%s", (setup["id"],))
			setup["communities"] = sorted([row["community"] for row in cur])
	return ret
