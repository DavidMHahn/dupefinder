"""READ-ONLY. Before removing an old backup set, list every file in it that
has NO identical copy in the set you keep.

It uses the report find_dupes made of the whole backup folder, so it does
not need to re-read any file contents: two files are identical if they are
in the same duplicate group of that report.

  1. Overview of every set (files, size, newest file date) to see which is live:
       py compare_backup_sets.py J:\\Toolkit\\Backup --report C:\\dupefinder\\ToolKitBackupFile.csv

  2. What would be lost by removing one set while keeping others:
       py compare_backup_sets.py J:\\Toolkit\\Backup --report C:\\dupefinder\\ToolKitBackupFile.csv
           --keep DESKTOP-A --keep DESKTOP-A_1 --check DESKTOP-B_1
     (--keep and --check can be repeated; without --check, every set not kept is checked)

Writes at_risk.csv (one row per file you would lose) in the current folder.
"""

import argparse
import csv
import os
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from .common import walk


@dataclass
class SetStats:
    name: str
    files: int = 0
    size: int = 0
    newest: float = 0.0


@dataclass
class Comparison:
    sets: list = field(default_factory=list)       # SetStats for every set
    at_risk: list = field(default_factory=list)    # (set, size, mtime, path)
    group_of: dict = field(default_factory=dict)   # normalised path -> report group

    @property
    def at_risk_bytes(self):
        return sum(r[1] for r in self.at_risk)

    @property
    def distinct_bytes(self):
        """At-risk bytes with identical at-risk copies counted once."""
        seen, unique = set(), 0
        for s, sz, mt, p in self.at_risk:
            g = self.group_of.get(os.path.normcase(os.path.abspath(p)))
            if g is None or g not in seen:
                unique += sz
                if g is not None:
                    seen.add(g)
        return unique


def list_sets(root):
    return sorted(e.name for e in os.scandir(root) if e.is_dir())


def compare(root, report, keep=(), check=()):
    """Walk every backup set under root and find files in the checked sets
    with no identical copy (same report group) in any kept set."""
    root = os.path.abspath(root)
    sets = list_sets(root)
    keep = set(keep)
    check = set(check) or (set(sets) - keep if keep else set())

    def set_of(path):
        return os.path.relpath(path, root).split(os.sep)[0]

    res = Comparison()
    group_sets = defaultdict(set)
    with open(report, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            p = os.path.normcase(os.path.abspath(row["path"]))
            res.group_of[p] = row["group"]
            group_sets[row["group"]].add(set_of(row["path"]))

    for s in sets:
        st = SetStats(s)
        for entry in walk(os.path.join(root, s)):
            info = entry.stat()
            sz, mt = info.st_size, info.st_mtime
            st.files += 1
            st.size += sz
            st.newest = max(st.newest, mt)
            if s in check and sz > 0:
                g = res.group_of.get(os.path.normcase(os.path.abspath(entry.path)))
                if g is None or not (keep & group_sets[g]):
                    res.at_risk.append((s, sz, mt, entry.path))
        res.sets.append(st)
    return res


def write_at_risk(at_risk, out):
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["set", "size_MB", "modified", "path"])
        for s, sz, mt, p in sorted(at_risk, key=lambda r: -r[1]):
            w.writerow([s, round(sz / 1e6, 3), time.strftime("%Y-%m-%d", time.localtime(mt)), p])


def main(argv=None):
    ap = argparse.ArgumentParser(description="Find files only present in old backup sets")
    ap.add_argument("root", help="folder holding the backup sets, e.g. J:\\Toolkit\\Backup")
    ap.add_argument("--report", required=True, help="find_dupes.py CSV made of that same folder")
    ap.add_argument("--keep", action="append", default=[], metavar="SET",
                    help="a backup set you keep (repeat for several)")
    ap.add_argument("--check", action="append", default=[], metavar="SET",
                    help="a set you are thinking of removing (default: every set not kept)")
    args = ap.parse_args(argv)

    root = os.path.abspath(args.root)
    sets = list_sets(root)
    for name in args.keep + args.check:
        if name not in sets:
            sys.exit(f"No set called {name!r} under {root}. Sets found: {', '.join(sets)}")

    res = compare(root, args.report, args.keep, args.check)
    print(f"{'set':<28}{'files':>10}{'GB':>10}  newest file")
    for st in res.sets:
        day = time.strftime("%Y-%m-%d", time.localtime(st.newest)) if st.newest else "-"
        print(f"{st.name:<28}{st.files:>10,}{st.size / 1e9:>10,.1f}  {day}")

    if not args.keep:
        print("\nThe set with the newest file date is most likely the live one.")
        print("Run again with --keep <that set> to see what the other sets hold that it does not.")
        return res

    out = os.path.abspath("at_risk.csv")
    write_at_risk(res.at_risk, out)
    check = set(args.check) or (set(sets) - set(args.keep))
    print(f"\nFiles in {', '.join(sorted(check))} with NO identical copy in "
          f"{', '.join(sorted(args.keep))}: {len(res.at_risk):,} files, "
          f"{res.at_risk_bytes / 1e9:,.2f} GB ({res.distinct_bytes / 1e9:,.2f} GB of distinct content)")
    by_folder = Counter()
    for s, sz, mt, p in res.at_risk:
        parts = os.path.relpath(p, root).split(os.sep)
        by_folder[os.sep.join(parts[:5])] += sz
    print("Largest folders of at-risk files:")
    for k, v in by_folder.most_common(15):
        print(f"  {v / 1e9:>8,.2f} GB  {k}")
    print(f"Full list: {out}")
    return res


if __name__ == "__main__":
    main()
