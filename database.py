import psycopg2
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
		id integer primary key,
		name text not null default '',
		descr text not null default ''
	)""",
	"""create table if not exists mustard.setup_communities (
		setupid integer not null references mustard.setups,
		community integer not null references mustard.communities
	)""",
)

def create_tables():
	with postgres, postgres.cursor() as cur:
		for tb in CREATE_TABLE:
			cur.execute(tb)
create_tables()
