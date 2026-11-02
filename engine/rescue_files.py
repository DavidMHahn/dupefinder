"""
rescue_files.py - move the at-risk files listed by compare_backup_sets.py
out of an old backup set into a plain folder, BEFORE that set is removed.

DRY RUN by default. Add --go to move. Moves stay on the same drive (instant,
nothing is copied), keep the folder structure, are logged, and --undo puts
them back.

  py rescue_files.py C:\\dupefinder\\at_risk.csv --dest J:\\Rescued_H8P3IB1 ^
      --include "C\\Users\\hahnd\\Videos" --include "C\\Users\\hahnd\\Desktop"
  (same command + --go to move)
  py rescue_files.py --undo C:\\dupefinder\\rescue_20261031_090000.csv

--include is a folder path relative to the backup set (as shown in the
"Largest folders" list without the set name). Repeat it for several.
"""

import argparse
import csv
import os
import sys
import time


def undo(log_path):
    with open(log_path, newline="", encoding="utf-8-sig") as f:
        rows = [r for r in csv.DictReader(f) if r["status"] == "moved"]
    back = 0
    for r in rows:
        src, dst = r["rescued_path"], r["original_path"]
        if not os.path.exists(src):
            print(f"  not in rescue folder, skipped: {src}")
        elif os.path.exists(dst):
            print(f"  something already at original path, skipped: {dst}")
        else:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            os.rename(src, dst)
            back += 1
    print(f"Restored {back:,} of {len(rows):,} files.")


def main():
    ap = argparse.ArgumentParser(description="Rescue at-risk files from an old backup set")
    ap.add_argument("at_risk", nargs="?", help="at_risk.csv from compare_backup_sets.py")
    ap.add_argument("--dest", help="plain folder to move them into, on the same drive")
    ap.add_argument("--include", action="append", default=[], metavar="FOLDER",
                    help="folder inside the set to rescue, e.g. C\\Users\\hahnd\\Videos")
    ap.add_argument("--go", action="store_true", help="actually move (default is a dry run)")
    ap.add_argument("--undo", metavar="RESCUE_LOG", help="move files back using a rescue log")
    args = ap.parse_args()

    if args.undo:
        return undo(args.undo)
    if not (args.at_risk and args.dest and args.include):
        ap.error("at_risk.csv, --dest and at least one --include are required")

    dest = os.path.abspath(args.dest)
    with open(args.at_risk, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    picked = []
    for r in rows:
        path = r["path"]
        marker = os.sep + r["set"] + os.sep
        if marker not in path:
            continue
        inside = path.split(marker, 1)[1]          # e.g. C\Users\hahnd\Videos\a.mp4
        for inc in args.include:
            inc = inc.strip("\\/")
            if inside.lower().startswith(inc.lower() + os.sep):
                picked.append((path, os.path.join(dest, r["set"], inside)))
                break

    if not picked:
        sys.exit("No at-risk files are under the --include folders. Check the spelling.")
    if os.path.splitdrive(picked[0][0])[0].lower() != os.path.splitdrive(dest)[0].lower():
        sys.exit("--dest must be on the same drive as the backup, so moves are instant.")

    print("MOVING FILES" if args.go else "DRY RUN (nothing will be moved; add --go to move)")
    log_path = os.path.abspath(
        f"{'rescue' if args.go else 'rescue_dryrun'}_{time.strftime('%Y%m%d_%H%M%S')}.csv")
    moved = skipped = total = 0
    with open(log_path, "w", newline="", encoding="utf-8-sig") as logf:
        log = csv.writer(logf)
        log.writerow(["status", "original_path", "rescued_path", "size_bytes"])
        for src, dst in picked:
            if not os.path.isfile(src):
                log.writerow(["skipped: no longer there", src, dst, ""])
                skipped += 1
                continue
            size = os.path.getsize(src)
            if os.path.exists(dst):
                log.writerow(["skipped: already in rescue folder", src, dst, size])
                skipped += 1
                continue
            status = "would move"
            if args.go:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                os.rename(src, dst)
                status = "moved"
            log.writerow([status, src, dst, size])
            moved += 1
            total += size

    verb = "Moved" if args.go else "Would move"
    print(f"{verb} {moved:,} files ({total / 1e9:,.2f} GB) into {dest}; skipped {skipped:,}.")
    print(f"Log: {log_path}")
    if args.go:
        print(f"To undo: py rescue_files.py --undo \"{log_path}\"")


if __name__ == "__main__":
    main()
