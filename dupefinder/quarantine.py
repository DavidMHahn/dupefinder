"""Act on a find_dupes report, SAFELY.

It never deletes anything. For each duplicate group it keeps one copy and
MOVES the others into a quarantine folder on the same drive, keeping their
original folder structure. A move within one drive is instant (no data is
copied). Every move is logged, and undo puts everything back.

By default it is a DRY RUN: it only prints and logs what it WOULD do.
Add --go to actually move files.

  py quarantine_dupes.py C:\\dupefinder\\dupes.csv --quarantine J:\\_dupes_quarantine
  py quarantine_dupes.py C:\\dupefinder\\dupes.csv --quarantine J:\\_dupes_quarantine --go
  py quarantine_dupes.py --undo C:\\dupefinder\\moves_20261030_150000.csv
  add --skip-name Folder.jpg --skip-name "AlbumArt*" --skip-name desktop.ini to leave album art alone

When you are happy nothing is missing (days or weeks later), delete the
quarantine folder yourself in Explorer.
"""

import argparse
import csv
import fnmatch
import os
import time
from collections import defaultdict
from dataclasses import dataclass

from .common import blake2b, under

LOG_COLUMNS = ["group", "status", "kept_path", "original_path", "quarantine_path", "size_bytes"]


@dataclass
class Outcome:
    moved: int = 0          # files moved (or that would move, in a dry run)
    skipped: int = 0
    freed: int = 0          # bytes
    log_path: str = ""


def choose_keeper(paths, rule, prefer):
    """Return the one path to keep. Ties fall back to alphabetical order."""
    paths = sorted(paths)
    if prefer:
        preferred = [p for p in paths if p.lower().startswith(prefer.lower())]
        if preferred:
            paths = preferred
    if rule == "shortest":                  # shallowest / shortest path
        return min(paths, key=lambda p: (p.count(os.sep), len(p)))
    if rule == "oldest":                    # earliest modified date
        return min(paths, key=os.path.getmtime)
    if rule == "newest":
        return max(paths, key=os.path.getmtime)
    return paths[0]                         # "alpha"


def quarantine_path(qroot, path):
    """J:\\Photos\\a.jpg -> J:\\_dupes_quarantine\\Photos\\a.jpg"""
    drive, rest = os.path.splitdrive(os.path.abspath(path))
    return os.path.join(qroot, rest.lstrip("\\/"))


def load_groups(report, qroot, skip_names=()):
    """Read a find_dupes report into {group: [paths]} and {group: (size, digest)}.

    Files already inside the quarantine are left out, so they can never be
    chosen as the kept copy. Files whose name matches a skip pattern are left
    out too (e.g. album art that belongs in each album folder)."""
    groups = defaultdict(list)
    meta = {}
    with open(report, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if under(row["path"], [qroot]):
                continue          # never keep, or move, a file already in quarantine
            name = os.path.basename(row["path"]).lower()
            if any(fnmatch.fnmatch(name, pat.lower()) for pat in skip_names):
                continue          # e.g. album art / desktop.ini that belongs in its folder
            groups[row["group"]].append(row["path"])
            meta[row["group"]] = (int(row["size_bytes"]), row["blake2b"])
    return groups, meta


def run(report, quarantine, keep="shortest", prefer=None, only_under=(), skip_names=(),
        verify=False, go=False, log_dir="."):
    """Plan (go=False) or carry out (go=True) the moves. Writes a CSV log and returns an Outcome."""
    qroot = os.path.abspath(quarantine)
    groups, meta = load_groups(report, qroot, skip_names)
    qdrive = os.path.splitdrive(qroot)[0].lower()

    out = Outcome()
    out.log_path = os.path.abspath(os.path.join(
        log_dir, f"{'moves' if go else 'dryrun'}_{time.strftime('%Y%m%d_%H%M%S')}.csv"))

    with open(out.log_path, "w", newline="", encoding="utf-8-sig") as logf:
        log = csv.writer(logf)
        log.writerow(LOG_COLUMNS)
        for g, paths in groups.items():
            size, digest = meta[g]
            existing = [p for p in paths if os.path.isfile(p) and os.path.getsize(p) == size]
            if len(existing) < 2:
                out.skipped += len(paths) - 1
                log.writerow([g, "skipped: fewer than 2 copies still present", "", "", "", size])
                continue
            outside = [p for p in existing if not under(p, only_under)]
            keeper = choose_keeper(outside or existing, keep, prefer)
            for p in existing:
                if p == keeper:
                    continue
                if only_under and not under(p, only_under):
                    log.writerow([g, "skipped: outside --only-under", keeper, p, "", size])
                    out.skipped += 1
                    continue
                if os.path.splitdrive(p)[0].lower() != qdrive:
                    # moving across drives would copy data; quarantine stays on one drive
                    log.writerow([g, "skipped: on a different drive than --quarantine", keeper, p, "", size])
                    out.skipped += 1
                    continue
                dest = quarantine_path(qroot, p)
                status = "would move"
                if go:
                    if verify and not (blake2b(p) == blake2b(keeper) == digest):
                        log.writerow([g, "skipped: contents changed since report", keeper, p, "", size])
                        out.skipped += 1
                        continue
                    if os.path.exists(dest):
                        log.writerow([g, "skipped: already in quarantine", keeper, p, dest, size])
                        out.skipped += 1
                        continue
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    os.rename(p, dest)
                    status = "moved"
                log.writerow([g, status, keeper, p, dest, size])
                out.moved += 1
                out.freed += size
    return out


def undo(log_path, log=print):
    """Move every file a moves log says was moved back to its original path.
    Returns (restored, total)."""
    with open(log_path, newline="", encoding="utf-8-sig") as f:
        rows = [r for r in csv.DictReader(f) if r["status"] == "moved"]
    back = 0
    for r in rows:
        src, dst = r["quarantine_path"], r["original_path"]
        if not os.path.exists(src) and os.path.exists(dst):
            log(f"  already back in place: {dst}")
        elif not os.path.exists(src):
            log(f"  missing in quarantine, skipped: {src}")
        elif os.path.exists(dst):
            log(f"  something already at original path, skipped: {dst}")
        else:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            os.rename(src, dst)
            back += 1
    log(f"Restored {back:,} of {len(rows):,} files.")
    return back, len(rows)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Move duplicate files to a quarantine folder")
    ap.add_argument("report", nargs="?", help="CSV written by find_dupes.py")
    ap.add_argument("--quarantine", help="folder to move extra copies into (same drive)")
    ap.add_argument("--keep", choices=["shortest", "oldest", "newest", "alpha"],
                    default="shortest", help="which copy to keep (default: shortest path)")
    ap.add_argument("--prefer", help="if a copy is under this folder, keep that one")
    ap.add_argument("--only-under", action="append", default=[], metavar="FOLDER",
                    help="only move copies under this folder (repeat for several); "
                         "the kept copy is then chosen from outside these folders when possible")
    ap.add_argument("--skip-name", action="append", default=[], metavar="PATTERN",
                    help="never move files whose name matches, e.g. --skip-name Folder.jpg "
                         "--skip-name \"AlbumArt*\" (repeat for several; case-insensitive)")
    ap.add_argument("--verify", action="store_true",
                    help="re-hash each file before moving it (slow, reads it again)")
    ap.add_argument("--go", action="store_true", help="actually move files (default is a dry run)")
    ap.add_argument("--undo", metavar="MOVES_LOG", help="move files back using a moves log")
    args = ap.parse_args(argv)

    if args.undo:
        return undo(args.undo)
    if not args.report or not args.quarantine:
        ap.error("report and --quarantine are required")

    print("MOVING FILES" if args.go else "DRY RUN (nothing will be moved; add --go to move)")
    out = run(args.report, args.quarantine, args.keep, args.prefer, args.only_under,
              args.skip_name, args.verify, args.go)
    verb = "Moved" if args.go else "Would move"
    print(f"{verb} {out.moved:,} files ({out.freed / 1e9:,.2f} GB); skipped {out.skipped:,}.")
    print(f"Log: {out.log_path}")
    if args.go:
        print(f"To undo: py quarantine_dupes.py --undo \"{out.log_path}\"")
    return out


if __name__ == "__main__":
    main()
