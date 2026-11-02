"""
compare_backup_sets.py - READ-ONLY. Before removing an old backup set,
list every file in it that has NO identical copy in the set you keep.

It uses the report find_dupes.py made of the whole backup folder, so it
does not need to re-read any file contents: two files are identical if
they are in the same duplicate group of that report.

  1. Overview of every set (files, size, newest file date) to see which is live:
       py compare_backup_sets.py J:\\Toolkit\\Backup --report C:\\dupefinder\\ToolKitBackupFile.csv

  2. What would be lost by removing one set while keeping others:
       py compare_backup_sets.py J:\\Toolkit\\Backup --report C:\\dupefinder\\ToolKitBackupFile.csv
           --keep DESKTOP-R9K909A --keep DESKTOP-R9K909A_1 --check DESKTOP-H8P3IB1_1
     (--keep and --check can be repeated; without --check, every set not kept is checked)

Writes at_risk.csv (one row per file you would lose) in the current folder.
"""

import argparse
import csv
import os
import sys
import time
from collections import defaultdict, Counter


def walk(folder):
    """Yield (path, size, mtime) of every file under folder, skipping links."""
    stack = [folder]
    while stack:
        d = stack.pop()
        try:
            with os.scandir(d) as entries:
                for e in entries:
                    try:
                        if e.is_symlink() or getattr(e, "is_junction", bool)():
                            continue
                        if e.is_dir():
                            stack.append(e.path)
                        elif e.is_file():
                            st = e.stat()
                            yield e.path, st.st_size, st.st_mtime
                    except OSError as err:
                        print(f"  skipped {e.path}: {err}", file=sys.stderr)
        except OSError as err:
            print(f"  cannot open folder {d}: {err}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser(description="Find files only present in old backup sets")
    ap.add_argument("root", help="folder holding the backup sets, e.g. J:\\Toolkit\\Backup")
    ap.add_argument("--report", required=True, help="find_dupes.py CSV made of that same folder")
    ap.add_argument("--keep", action="append", default=[], metavar="SET",
                    help="a backup set you keep (repeat for several)")
    ap.add_argument("--check", action="append", default=[], metavar="SET",
                    help="a set you are thinking of removing (default: every set not kept)")
    args = ap.parse_args()

    root = os.path.abspath(args.root)
    sets = sorted(e.name for e in os.scandir(root) if e.is_dir())
    for name in args.keep + args.check:
        if name not in sets:
            sys.exit(f"No set called {name!r} under {root}. Sets found: {', '.join(sets)}")
    keep = set(args.keep)
    check = set(args.check) or (set(sets) - keep if keep else set())

    def set_of(path):
        rel = os.path.relpath(path, root)
        return rel.split(os.sep)[0]

    # Which sets hold a copy of each duplicate group?
    group_of = {}
    group_sets = defaultdict(set)
    with open(args.report, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            p = os.path.normcase(os.path.abspath(row["path"]))
            group_of[p] = row["group"]
            group_sets[row["group"]].add(set_of(row["path"]))

    print(f"{'set':<28}{'files':>10}{'GB':>10}  newest file")
    at_risk = []
    for s in sets:
        n = size = 0
        newest = 0
        for path, sz, mt in walk(os.path.join(root, s)):
            n += 1
            size += sz
            newest = max(newest, mt)
            if s in check and sz > 0:
                g = group_of.get(os.path.normcase(os.path.abspath(path)))
                if g is None or not (keep & group_sets[g]):
                    at_risk.append((s, sz, mt, path))
        day = time.strftime("%Y-%m-%d", time.localtime(newest)) if newest else "-"
        print(f"{s:<28}{n:>10,}{size / 1e9:>10,.1f}  {day}")

    if not keep:
        print("\nThe set with the newest file date is most likely the live one.")
        print("Run again with --keep <that set> to see what the other sets hold that it does not.")
        return

    out = os.path.abspath("at_risk.csv")
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["set", "size_MB", "modified", "path"])
        for s, sz, mt, p in sorted(at_risk, key=lambda r: -r[1]):
            w.writerow([s, round(sz / 1e6, 3), time.strftime("%Y-%m-%d", time.localtime(mt)), p])

    total = sum(r[1] for r in at_risk)
    seen, unique = set(), 0          # count identical at-risk copies only once
    for s, sz, mt, p in at_risk:
        g = group_of.get(os.path.normcase(os.path.abspath(p)))
        if g is None or g not in seen:
            unique += sz
            if g is not None:
                seen.add(g)
    print(f"\nFiles in {', '.join(sorted(check))} with NO identical copy in {', '.join(sorted(keep))}: "
          f"{len(at_risk):,} files, {total / 1e9:,.2f} GB "
          f"({unique / 1e9:,.2f} GB of distinct content)")
    by_folder = Counter()
    for s, sz, mt, p in at_risk:
        parts = os.path.relpath(p, root).split(os.sep)
        by_folder[os.sep.join(parts[:5])] += sz
    print("Largest folders of at-risk files:")
    for k, v in by_folder.most_common(15):
        print(f"  {v / 1e9:>8,.2f} GB  {k}")
    print(f"Full list: {out}")


if __name__ == "__main__":
    main()
