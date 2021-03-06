import queue
import threading
import time

class ScheduleQueue(queue.PriorityQueue):
	"""Variant of queue.PriorityQueue where the priorities are times.

	Entries are tuples of the form (time, data...). Any entry whose time
	is in the future is treated as not yet in the queue. The perceived
	length of the queue is either zero (nothing is at time yet) or one
	(there's at least one element, and it is now due).
	"""
	def _qsize(self):
		if not self.queue: return 0
		if self.queue[0][0] > time.time(): return 0
		return 1

	def maxwait(self):
		"""Bound the timeout to the shortest event in queue"""
		if not self.queue: return None
		return self.queue[0][0] - time.time()

	def wait(self):
		"""Like self.get(True, None) but respects chronology"""
		with self.not_empty:
			while not self._qsize():
				self.not_empty.wait(self.maxwait())
			item = self._get()
			self.not_full.notify()
			return item

class Scheduler:
	"""Self-pumping schedule queue"""
	def __init__(self):
		self.queue = ScheduleQueue()
		self.thread = threading.Thread(target=self.pump)
		self.thread.daemon = True
		self.counter = 0
		self.deleted = {}
		self.thread.start()

	def pump(self):
		while True:
			tm, func, id, args = self.queue.wait()
			assert tm <= time.time()
			if self.deleted.pop(id, False): continue # Deleted event
			func(*args)

	def put(self, tm, func, *args):
		self.counter += 1
		return self.queue.put((tm, func, self.counter, args))

	def search(self, func):
		"""Return a list of all queued calls to a given function"""
		return [(t, i, a) for t, f, i, a in self.queue.queue if f is func and i not in self.deleted]

	def remove(self, id):
		self.deleted[id] = True
