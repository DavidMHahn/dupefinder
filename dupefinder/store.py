"""A small SQLite database for scan data.

Four jobs:

1. Hash cache. Every hash the finder computes is saved with the file's path,
   size and modified time. A later scan reuses it when the size and modified
   time are unchanged, so an unchanged drive is not read again. Hashes are
   committed every few seconds, so a scan that is interrupted (unplugged
   drive, sleep, Ctrl+C) keeps the work it had done: run it again and it
   carries on from there.

2. Saved scans. Each finished scan is stored with its date, folders, options,
   the dupefinder version that made it, and its duplicate groups, so a review
   screen can list and reload past scans without re-reading a CSV.

3. Keeper choices. The rules and hand-picked keepers chosen for a scan, so
   the person can leave and come back, and the Dry run step can use them.

4. Dry runs. Every planned move with its checks, so the Quarantine step
   carries out exactly what the person previewed.

The database lives OUTSIDE the scanned folders (the finder refuses otherwise),
and it never stores file contents, only paths, sizes, dates and hashes.

Caveat: a file changed without its size or modified time changing would keep
its old hash. That is rare; quarantine --verify re-hashes both copies before
moving anything, so it cannot cause a wrong move.
"""

import json
import os
import sqlite3
import time

from . import __version__

SCHEMA = """
CREATE TABLE IF NOT EXISTS hashes (
    path      TEXT PRIMARY KEY,   -- normalised: absolute and case-folded on Windows
    size      INTEGER NOT NULL,
    mtime_ns  INTEGER NOT NULL,
    partial   TEXT,               -- BLAKE2b of the first 64 KB
    full      TEXT                -- BLAKE2b of the whole file
);
CREATE TABLE IF NOT EXISTS scans (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    started   TEXT NOT NULL,      -- local time, YYYY-MM-DD HH:MM:SS
    finished  TEXT,
    version   TEXT NOT NULL,      -- dupefinder version that made the scan
    roots     TEXT NOT NULL,      -- JSON list
    options   TEXT NOT NULL,      -- JSON object
    n_files   INTEGER,
    n_bytes   INTEGER,
    wasted    INTEGER
);
CREATE TABLE IF NOT EXISTS scan_files (
    scan_id   INTEGER NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
    grp       INTEGER NOT NULL,   -- 1 = most wasted space
    size      INTEGER NOT NULL,
    digest    TEXT NOT NULL,
    path      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS scan_files_scan ON scan_files(scan_id, grp);
CREATE TABLE IF NOT EXISTS keeper_rules (
    scan_id   INTEGER PRIMARY KEY REFERENCES scans(id) ON DELETE CASCADE,
    rules     TEXT NOT NULL,      -- JSON: keepers.Rules
    updated   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS keeper_picks (
    scan_id   INTEGER NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
    grp       INTEGER NOT NULL,
    path      TEXT NOT NULL,      -- the copy the person chose to keep by hand
    PRIMARY KEY (scan_id, grp)
);
CREATE TABLE IF NOT EXISTS dry_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id     INTEGER NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
    created     TEXT NOT NULL,
    quarantines TEXT NOT NULL,    -- JSON: {drive: quarantine folder}
    n_moves     INTEGER NOT NULL,
    freed       INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS dry_run_moves (
    dry_run_id  INTEGER NOT NULL REFERENCES dry_runs(id) ON DELETE CASCADE,
    grp         INTEGER NOT NULL,
    status      TEXT NOT NULL,
    kept        TEXT NOT NULL,
    original    TEXT NOT NULL,
    dest        TEXT NOT NULL,
    size        INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS dry_run_moves_run ON dry_run_moves(dry_run_id);
"""

COMMIT_SECONDS = 5.0
KINDS = ("partial", "full")       # the only column names ever put into SQL text


def _key(path):
    return os.path.normcase(os.path.abspath(path))


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


class Store:
    """Open (or create) the database at db_path. Use as a context manager."""

    def __init__(self, db_path):
        self.path = os.path.abspath(db_path)
        self.db = sqlite3.connect(self.path)
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript(SCHEMA)
        self.db.commit()
        self.hits = 0           # hashes reused from the cache in this session
        self.misses = 0         # hashes that had to be read from disk
        self._last_commit = time.monotonic()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        if self.db is not None:
            self.db.commit()
            self.db.close()
            self.db = None

    # ------------------------------------------------------------ hash cache
    def cached(self, path, size, mtime_ns, kind):
        """Return the cached 'partial' or 'full' hash, or None if absent or stale."""
        assert kind in KINDS
        row = self.db.execute(
            f"SELECT {kind} FROM hashes WHERE path = ? AND size = ? AND mtime_ns = ?",
            (_key(path), size, mtime_ns)).fetchone()
        return row[0] if row else None

    def remember(self, path, size, mtime_ns, kind, digest):
        """Save a hash. A changed size or date replaces the old entry entirely."""
        assert kind in KINDS
        k = _key(path)
        row = self.db.execute("SELECT size, mtime_ns FROM hashes WHERE path = ?", (k,)).fetchone()
        if row is None or tuple(row) != (size, mtime_ns):
            self.db.execute("INSERT OR REPLACE INTO hashes (path, size, mtime_ns, partial, full) "
                            "VALUES (?, ?, ?, NULL, NULL)", (k, size, mtime_ns))
        self.db.execute(f"UPDATE hashes SET {kind} = ? WHERE path = ?", (digest, k))
        if time.monotonic() - self._last_commit > COMMIT_SECONDS:
            self.commit()

    def commit(self):
        self.db.commit()
        self._last_commit = time.monotonic()

    def hash_with_cache(self, hasher, path, size, mtime_ns, kind, limit=None):
        """Return the hash of path, from the cache when its size and date are unchanged."""
        digest = self.cached(path, size, mtime_ns, kind)
        if digest is not None:
            self.hits += 1
            return digest
        digest = hasher(path, limit) if limit else hasher(path)
        self.misses += 1
        if digest is not None:
            self.remember(path, size, mtime_ns, kind, digest)
        return digest

    # ------------------------------------------------------------ saved scans
    def save_scan(self, roots, options, result, started):
        """Store a finished ScanResult. Returns the new scan id."""
        cur = self.db.execute(
            "INSERT INTO scans (started, finished, version, roots, options, n_files, n_bytes, wasted) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (started, _now(), __version__, json.dumps(list(roots)), json.dumps(options),
             result.n_files, result.n_bytes, result.wasted))
        scan_id = cur.lastrowid
        self.db.executemany(
            "INSERT INTO scan_files (scan_id, grp, size, digest, path) VALUES (?, ?, ?, ?, ?)",
            ((scan_id, i, g.size, g.digest, p)
             for i, g in enumerate(result.groups, 1) for p in g.paths))
        self.commit()
        return scan_id

    def list_scans(self):
        """Newest first: dicts with id, started, finished, version, roots, n_files, wasted."""
        rows = self.db.execute(
            "SELECT id, started, finished, version, roots, options, n_files, n_bytes, wasted "
            "FROM scans ORDER BY id DESC").fetchall()
        cols = ["id", "started", "finished", "version", "roots", "options", "n_files", "n_bytes", "wasted"]
        out = []
        for r in rows:
            d = dict(zip(cols, r))
            d["roots"] = json.loads(d["roots"])
            d["options"] = json.loads(d["options"])
            out.append(d)
        return out

    def load_groups(self, scan_id):
        """Return the scan's duplicate groups as finder.Group objects, most wasted first."""
        from .finder import Group
        groups = {}
        for grp, size, digest, path in self.db.execute(
                "SELECT grp, size, digest, path FROM scan_files WHERE scan_id = ? "
                "ORDER BY grp, path", (scan_id,)):
            groups.setdefault(grp, Group(size, [], digest)).paths.append(path)
        return [groups[k] for k in sorted(groups)]

    # ------------------------------------------------------------ keeper choices
    def save_choices(self, scan_id, rules, picks):
        """Save a scan's keeper rules (a dict) and hand picks ({group number: path})."""
        self.db.execute("INSERT OR REPLACE INTO keeper_rules (scan_id, rules, updated) VALUES (?, ?, ?)",
                        (scan_id, json.dumps(rules), _now()))
        self.db.execute("DELETE FROM keeper_picks WHERE scan_id = ?", (scan_id,))
        self.db.executemany("INSERT INTO keeper_picks (scan_id, grp, path) VALUES (?, ?, ?)",
                            ((scan_id, g, p) for g, p in sorted(picks.items())))
        self.commit()

    def load_choices(self, scan_id):
        """Return (rules dict or None, {group number: path}) for a scan."""
        row = self.db.execute("SELECT rules FROM keeper_rules WHERE scan_id = ?", (scan_id,)).fetchone()
        picks = dict(self.db.execute("SELECT grp, path FROM keeper_picks WHERE scan_id = ?", (scan_id,)))
        return (json.loads(row[0]) if row else None), picks

    def choices_updated(self, scan_id):
        """When the scan's keeper choices were last saved, or None."""
        row = self.db.execute("SELECT updated FROM keeper_rules WHERE scan_id = ?", (scan_id,)).fetchone()
        return row[0] if row else None

    # ------------------------------------------------------------ dry runs
    def save_dry_run(self, scan_id, dry):
        """Store a dryrun.DryRun. Returns its id."""
        cur = self.db.execute(
            "INSERT INTO dry_runs (scan_id, created, quarantines, n_moves, freed) VALUES (?, ?, ?, ?, ?)",
            (scan_id, _now(), json.dumps(dry.quarantines), len(dry.moving), dry.freed))
        run_id = cur.lastrowid
        self.db.executemany(
            "INSERT INTO dry_run_moves (dry_run_id, grp, status, kept, original, dest, size) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ((run_id, m.group, m.status, m.kept, m.original, m.dest, m.size) for m in dry.moves))
        self.commit()
        return run_id

    def latest_dry_run(self, scan_id):
        """The newest dry run of a scan as (id, created, DryRun), or None."""
        from .dryrun import DryRun, Move
        row = self.db.execute("SELECT id, created, quarantines FROM dry_runs WHERE scan_id = ? "
                              "ORDER BY id DESC LIMIT 1", (scan_id,)).fetchone()
        if not row:
            return None
        run_id, created, quarantines = row
        moves = [Move(*r) for r in self.db.execute(
            "SELECT grp, status, kept, original, dest, size FROM dry_run_moves "
            "WHERE dry_run_id = ? ORDER BY rowid", (run_id,))]
        return run_id, created, DryRun(moves, json.loads(quarantines))
