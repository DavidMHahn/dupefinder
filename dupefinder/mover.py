"""Carry out a saved dry run: move extra copies into quarantine. Never deletes.

Only moves the dry run marked "would move", and checks each one again just
before moving it (the same checks as the dry run). With verify=True it also
re-reads the copy and the kept copy and moves only if they are still
byte-for-byte identical.

Every move is written to a moves log as it happens (flushed each row), in
the format quarantine_dupes.py and verify_quarantine.py use, so a crash or a
pulled plug leaves an accurate log, and undo() puts everything back.
"""

import csv
import os
import time
from dataclasses import dataclass

from . import dryrun
from .common import blake2b
from .quarantine import LOG_COLUMNS, undo  # noqa: F401  (undo is part of this module's API)

MOVED = "moved"
SKIP_CHANGED = "skipped: contents changed since the dry run"


class Stopped(Exception):
    """Raised by a progress callback to stop between two files."""


@dataclass
class Result:
    moved: int = 0
    freed: int = 0
    skipped: int = 0
    stopped: bool = False
    log_path: str = ""


def log_name(log_dir):
    return os.path.join(log_dir, f"moves_{time.strftime('%Y%m%d_%H%M%S')}.csv")


def run(dry, log_path, verify=True, progress=None):
    """Move every "would move" copy of a DryRun. progress(done, total) may raise
    Stopped to stop between two files; what was moved stays moved and logged."""
    todo = [m for m in dry.moves if m.would_move]
    qroots = [os.path.abspath(q) for q in dry.quarantines.values()]
    qdev = {v: dryrun._device(q) for v, q in dry.quarantines.items()}
    kept_hash = {}
    res = Result(log_path=os.path.abspath(log_path))
    os.makedirs(os.path.dirname(res.log_path), exist_ok=True)
    with open(res.log_path, "w", newline="", encoding="utf-8-sig") as f:
        log = csv.writer(f)
        log.writerow(LOG_COLUMNS)
        f.flush()
        for i, m in enumerate(todo):
            if progress:
                try:
                    progress(i, len(todo))
                except Stopped:
                    res.stopped = True
                    break
            v = dryrun.volume(m.original)
            kept_ok = dryrun._size(m.kept) == m.size
            status = dryrun.check(m.kept, kept_ok, m.original, m.size, m.dest, qroots, qdev.get(v))
            if status == dryrun.WOULD_MOVE and verify:
                try:
                    if m.kept not in kept_hash:
                        kept_hash[m.kept] = blake2b(m.kept)
                    same = blake2b(m.original) == kept_hash[m.kept]
                except OSError as e:
                    same, status = False, f"skipped: could not read ({e.strerror or e})"
                if not same and status == dryrun.WOULD_MOVE:
                    status = SKIP_CHANGED
            if status == dryrun.WOULD_MOVE:
                try:
                    os.makedirs(os.path.dirname(m.dest), exist_ok=True)
                    os.rename(m.original, m.dest)     # same drive: instant, no data copied
                    status = MOVED
                except OSError as e:
                    status = f"skipped: could not move ({e.strerror or e})"
            if status == MOVED:
                res.moved += 1
                res.freed += m.size
            else:
                res.skipped += 1
            log.writerow([m.group, status, m.kept, m.original, m.dest if status == MOVED else "", m.size])
            f.flush()
        if progress and not res.stopped:
            progress(len(todo), len(todo))
    return res
