"""Preview every move before anything is moved. READ-ONLY.

Takes the keeper plan (see keepers.py) and checks each copy that would go to
quarantine, exactly as the Quarantine step will before it moves anything:

  - the copy is still there with the same size, and so is the kept copy
  - the copy is not inside a backup program's folder (those expect their
    own layout, so they are never cleaned)
  - the copy is on the same drive as its quarantine folder, so the move is
    instant and copies no data
  - nothing is already at the quarantine path

Each drive gets its own quarantine folder, by default _dupes_quarantine at the
top of that drive (J:\\_dupes_quarantine). A copy moves to the same path inside
it: J:\\Photos\\a.jpg -> J:\\_dupes_quarantine\\Photos\\a.jpg.

The result can be written as a CSV in the same format as quarantine_dupes.py
writes for a dry run.
"""

import csv
import os
from collections import Counter
from dataclasses import dataclass, field

from .common import under
from .keepers import MOVE
from .quarantine import LOG_COLUMNS

QUARANTINE_NAME = "_dupes_quarantine"

WOULD_MOVE = "would move"
SKIP_GONE = "skipped: file no longer there or changed"
SKIP_KEEPER_GONE = "skipped: kept copy no longer there or changed"
SKIP_KEEPER_IN_Q = "skipped: kept copy is inside a quarantine folder"
SKIP_IN_Q = "skipped: already inside a quarantine folder"
SKIP_BACKUP = "skipped: inside a backup program's folder"
SKIP_OTHER_DRIVE = "skipped: on a different drive than its quarantine folder"
SKIP_DEST = "skipped: something is already at the quarantine path"

# Folders that backup programs manage. Folder names, compared case-insensitively.
# File History, Windows Backup (system images), Samsung Smart Switch, macOS Time Machine.
BACKUP_FOLDER_NAMES = {"filehistory", "windowsimagebackup", "smartswitch", "smart switch",
                       "backups.backupdb"}
# Seagate Toolkit keeps its backups in Toolkit\Backup.
BACKUP_FOLDER_PAIRS = {("toolkit", "backup")}


def in_backup_folder(path):
    parts = [p.lower() for p in os.path.normpath(os.path.dirname(path)).split(os.sep) if p]
    if BACKUP_FOLDER_NAMES.intersection(parts):
        return True
    return any(pair in BACKUP_FOLDER_PAIRS for pair in zip(parts, parts[1:]))


def volume(path):
    """The drive a path is on: 'J:\\' on Windows, the mount point elsewhere."""
    path = os.path.abspath(path)
    drive = os.path.splitdrive(path)[0]
    if drive:
        return drive + os.sep
    while not os.path.ismount(path):
        parent = os.path.dirname(path)
        if parent == path:
            break
        path = parent
    return path


def default_quarantine(vol):
    return os.path.join(vol, QUARANTINE_NAME)


def quarantine_path(qroot, vol, path):
    """J:\\Photos\\a.jpg -> J:\\_dupes_quarantine\\Photos\\a.jpg"""
    return os.path.join(qroot, os.path.relpath(os.path.abspath(path), vol))


def _device(path):
    """st_dev of path, or of its nearest existing parent (the quarantine may not exist yet)."""
    while True:
        try:
            return os.stat(path).st_dev
        except OSError:
            parent = os.path.dirname(path)
            if parent == path:
                return None
            path = parent


def _size(path):
    try:
        return os.path.getsize(path) if os.path.isfile(path) else None
    except OSError:
        return None


@dataclass
class Move:
    group: int
    status: str
    kept: str
    original: str
    dest: str
    size: int

    @property
    def would_move(self):
        return self.status == WOULD_MOVE


@dataclass
class DryRun:
    moves: list = field(default_factory=list)
    quarantines: dict = field(default_factory=dict)      # volume -> quarantine folder

    @property
    def moving(self):
        return [m for m in self.moves if m.would_move]

    @property
    def freed(self):
        return sum(m.size for m in self.moves if m.would_move)

    @property
    def skipped(self):
        return [m for m in self.moves if not m.would_move]

    def reasons(self):
        """{skip reason: count}, most common first."""
        return dict(Counter(m.status for m in self.skipped).most_common())


def volumes(plans):
    """{volume: number of copies the plan would move from it}, in path order."""
    counts = Counter(volume(p) for gp in plans for p, s in gp.status.items() if s == MOVE)
    return dict(sorted(counts.items()))


def run(plans, quarantines=None, progress=None):
    """Check every planned move. quarantines maps volume -> folder (defaults filled in).
    progress(done, total) is called now and then."""
    vols = volumes(plans)
    q = {v: os.path.abspath((quarantines or {}).get(v) or default_quarantine(v)) for v in vols}
    qroots = list(q.values())
    qdev = {v: _device(folder) for v, folder in q.items()}
    out = DryRun(quarantines=q)
    total = sum(vols.values())
    done = 0
    for gp in plans:
        movers = [p for p, s in gp.status.items() if s == MOVE]
        if not movers:
            continue
        kept = gp.keeper
        kept_ok = _size(kept) == gp.size
        for p in movers:
            done += 1
            if progress and done % 200 == 0:
                progress(done, total)
            v = volume(p)
            dest = quarantine_path(q[v], v, p)
            if under(kept, qroots):
                status = SKIP_KEEPER_IN_Q
            elif under(p, qroots):
                status = SKIP_IN_Q
            elif in_backup_folder(p):
                status = SKIP_BACKUP
            elif _size(p) != gp.size:
                status = SKIP_GONE
            elif not kept_ok:
                status = SKIP_KEEPER_GONE
            elif _device(p) != qdev[v]:
                status = SKIP_OTHER_DRIVE
            elif os.path.lexists(dest):
                status = SKIP_DEST
            else:
                status = WOULD_MOVE
            out.moves.append(Move(gp.number, status, kept, p,
                                  dest if status in (WOULD_MOVE, SKIP_DEST) else "", gp.size))
    if progress:
        progress(total, total)
    return out


def write_log(dry, path):
    """Write the dry run as CSV, in quarantine_dupes.py's log format."""
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(LOG_COLUMNS)
        for m in dry.moves:
            w.writerow([m.group, m.status, m.kept, m.original, m.dest, m.size])
    return path
