# Load up gunicorn, just like running the command does, but with
# gevent monkeypatched first. Prevents startup warning and possible
# recursion errors.
import sys
from gevent import monkey; monkey.patch_all(subprocess=True)

from gunicorn.app.wsgiapp import run
sys.argv[0] = "gunicorn"
sys.exit(run())
