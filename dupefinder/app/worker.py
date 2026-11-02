"""Runs a scan in a background thread so the window stays responsive."""

import os
import sys
import time

from PySide6.QtCore import QObject, Signal

from ..finder import ScanCancelled, find_duplicates
from ..store import Store

APP_NAME = "dupefinder"


def default_db_path():
    """Where the app keeps its database: %LOCALAPPDATA%\\dupefinder on Windows."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, APP_NAME, "dupefinder.db")


class ScanWorker(QObject):
    """Call run() in a QThread. Emits progress while it works, then exactly one of
    finished(result, scan_id), cancelled() or failed(message)."""

    progress = Signal(int, int, int)        # stage (1, 3 or 4), done, total (-1 = unknown)
    finished = Signal(object, int)
    cancelled = Signal()
    failed = Signal(str)

    UPDATE_SECONDS = 0.1                    # don't flood the window with updates

    def __init__(self, roots, excludes=(), min_size=1, db_path=None):
        super().__init__()
        self.roots = [os.path.abspath(r) for r in roots]
        self.db_path = os.path.abspath(db_path or default_db_path())
        # never read the app's own database while it is being written
        self.excludes = list(excludes) + [os.path.dirname(self.db_path)]
        self.min_size = min_size
        self._stop = False
        self._last = 0.0
        self._stage = 0

    def stop(self):
        """Ask the scan to stop at the next file. Work done so far is kept."""
        self._stop = True

    def _progress(self, stage, done, total):
        if self._stop:
            raise ScanCancelled()
        now = time.monotonic()
        if stage != self._stage or done == total or now - self._last >= self.UPDATE_SECONDS:
            self._stage, self._last = stage, now
            self.progress.emit(stage, done, -1 if total is None else total)

    def run(self):
        started = time.strftime("%Y-%m-%d %H:%M:%S")
        try:
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
            with Store(self.db_path) as store:
                res = find_duplicates(self.roots, self.min_size, self.excludes, log=None,
                                      store=store, progress=self._progress)
                options = {"min_size": self.min_size, "exclude": self.excludes}
                scan_id = store.save_scan(self.roots, options, res, started)
        except ScanCancelled:
            self.cancelled.emit()
            return
        except Exception as e:          # shown to the person, never a crash
            self.failed.emit(f"{type(e).__name__}: {e}")
            return
        self.finished.emit(res, scan_id)
