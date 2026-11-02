"""Permanently delete what a quarantine run moved. The ONLY code that deletes files.

It deletes nothing but the files a moves log says were moved into quarantine,
and only when, at that moment, the copy is still in quarantine and its kept
copy is still there with the same size. Anything else stays where it is and
is reported. Folders inside the quarantine that end up empty are removed.
Every deletion is written to a log as it happens.

The app only calls this after the wait and a fresh SAFE verify.
"""

import csv
import os
import time
from dataclasses import dataclass, field

from .common import under

DELETED = "deleted"
SKIP_NOT_THERE = "kept: no longer in quarantine (put back or already removed)"
SKIP_KEPT_MISSING = "kept: KEPT COPY MISSING, so this is the last copy"
SKIP_KEPT_CHANGED = "kept: KEPT COPY CHANGED SIZE, so this may be the last good copy"
SKIP_ERROR = "kept: could not delete"
DELETE_COLUMNS = ["status", "quarantine_path", "kept_path", "size_bytes"]


class Stopped(Exception):
    pass


@dataclass
class Result:
    deleted: int = 0
    freed: int = 0
    kept: list = field(default_factory=list)      # (status, quarantine_path) left in place
    stopped: bool = False
    log_path: str = ""


def log_name(log_dir):
    return os.path.join(log_dir, f"deleted_{time.strftime('%Y%m%d_%H%M%S')}.csv")


def moved_rows(moves_log):
    with open(moves_log, newline="", encoding="utf-8-sig") as f:
        return [r for r in csv.DictReader(f) if r["status"] == "moved"]


def _prune(folder, roots):
    """Remove folder and its parents while empty, never going above a quarantine root."""
    roots = [os.path.normcase(os.path.abspath(r)) for r in roots]
    while folder and (os.path.normcase(folder) in roots or under(folder, roots)):
        try:
            os.rmdir(folder)              # only succeeds when empty
        except OSError:
            return
        if os.path.normcase(folder) in roots:
            return
        folder = os.path.dirname(folder)


def run(moves_log, qroots, out_log, progress=None):
    """Delete the quarantined copies listed in moves_log. qroots: the quarantine folders
    (only files inside them are ever deleted). progress(done, total) may raise Stopped."""
    rows = moved_rows(moves_log)
    res = Result(log_path=os.path.abspath(out_log))
    os.makedirs(os.path.dirname(res.log_path), exist_ok=True)
    with open(res.log_path, "w", newline="", encoding="utf-8-sig") as f:
        log = csv.writer(f)
        log.writerow(DELETE_COLUMNS)
        f.flush()
        for i, r in enumerate(rows):
            if progress:
                try:
                    progress(i, len(rows))
                except Stopped:
                    res.stopped = True
                    break
            quar, kept, size = r["quarantine_path"], r["kept_path"], int(r["size_bytes"])
            if not under(quar, qroots) or not os.path.isfile(quar):
                status = SKIP_NOT_THERE
            elif not os.path.isfile(kept):
                status = SKIP_KEPT_MISSING
            elif os.path.getsize(kept) != os.path.getsize(quar):
                status = SKIP_KEPT_CHANGED
            else:
                try:
                    os.remove(quar)
                    status = DELETED
                except OSError as e:
                    status = f"{SKIP_ERROR} ({e.strerror or e})"
            if status == DELETED:
                res.deleted += 1
                res.freed += size
                _prune(os.path.dirname(quar), qroots)
            else:
                res.kept.append((status, quar))
            log.writerow([status, quar, kept, size])
            f.flush()
        if progress and not res.stopped:
            progress(len(rows), len(rows))
    return res


# ---------------------------------------------------------------- when deleting is allowed
FMT = "%Y-%m-%d %H:%M:%S"
FRESH_HOURS = 24          # a SAFE check older than this must be run again


def _t(text):
    from datetime import datetime
    return datetime.strptime(text, FMT)


def wait_ends(run):
    """When the waiting time of a quarantine run (dict from Store.quarantine_runs) is over."""
    from datetime import timedelta
    return _t(run["finished"] or run["started"]) + timedelta(days=run["wait_days"])


def checks(run, last_verification, now=None):
    """The conditions for deleting a run's quarantine, as [(passed, text)].
    last_verification is (checked time text, Verdict) or None."""
    from datetime import datetime, timedelta
    now = now or datetime.now()
    out = []
    out.append((run["finished"] is not None and not run["undone"] and not run["deleted"],
                "The move finished and was not put back or deleted already"))
    ends = wait_ends(run)
    left = ends - now
    if left.total_seconds() > 0:
        days = left.days + (1 if left.seconds else 0)
        out.append((False, f"Waited {run['wait_days']} days: {days} more day{'s' if days != 1 else ''} "
                           f"(until {ends:%b %d, %Y %I:%M %p})"))
    else:
        out.append((True, f"Waited {run['wait_days']} days (since {_t(run['finished'] or run['started']):%b %d})"))
    if last_verification is None:
        out.append((False, "A SAFE check after the wait: not checked yet"))
    else:
        checked, verdict = last_verification
        when = _t(checked)
        if not verdict.safe:
            out.append((False, f"A SAFE check after the wait: the last check ({when:%b %d %I:%M %p}) was NOT SAFE"))
        elif when < ends:
            out.append((False, "A SAFE check after the wait: the last SAFE check was before the wait ended"))
        elif now - when > timedelta(hours=FRESH_HOURS):
            out.append((False, f"A SAFE check after the wait: the last one is over {FRESH_HOURS} hours old"))
        else:
            out.append((True, f"A SAFE check after the wait ({when:%b %d %I:%M %p})"))
    return out
