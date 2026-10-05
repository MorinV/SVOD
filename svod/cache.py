"""Memory of one run: git results and derived values, shared by every context of the run.

Nothing is written to disk: hooks and sessions run in parallel, a file would go stale.
"""
import threading
from concurrent.futures import ThreadPoolExecutor

from . import git

GIT_WORKERS = 8


class RunCache:
    """Git results by directory and arguments, and computed values by key, for one run."""

    def __init__(self):
        """Empty memory."""
        self._git = {}
        self._values = {}
        self._lock = threading.Lock()

    def git(self, cwd, *args):
        """Result of git in cwd with the arguments; run once per run."""
        key = (str(cwd), args)
        with self._lock:
            if key in self._git:
                return self._git[key]
        result = git.run_git(cwd, *args)
        with self._lock:
            return self._git.setdefault(key, result)

    def prefetch(self, calls):
        """Run the (cwd, args) git calls not yet known, in parallel."""
        with self._lock:
            todo = [c for c in dict.fromkeys((str(cwd), tuple(args)) for cwd, args in calls)
                    if c not in self._git]
        if len(todo) < 2:
            for cwd, args in todo:
                self.git(cwd, *args)
            return
        with ThreadPoolExecutor(max_workers=min(GIT_WORKERS, len(todo))) as pool:
            list(pool.map(lambda call: self.git(call[0], *call[1]), todo))

    def value(self, key, compute):
        """Value under the key, computed on first use."""
        with self._lock:
            if key in self._values:
                return self._values[key]
        found = compute()
        with self._lock:
            return self._values.setdefault(key, found)
