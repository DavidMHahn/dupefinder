"""READ-ONLY duplicate file finder.

It never deletes, moves, renames or writes to the folders it scans.
The only file it creates is the CSV report.

Pipeline (each stage only looks at what survived the previous one):
  1. Walk the folders and record every file's size        (no file contents read)
  2. Keep only sizes shared by 2+ files                     (no file contents read)
  3. Hash the first 64 KB of each remaining file            (small read per file)
  4. Fully hash files whose first 64 KB still match         (big reads, only where needed)
  5. Write groups of identical files to a CSV report

Usage (Windows):
  py find_dupes.py E:\\ --out dupes.csv
  py find_dupes.py "E:\\Photos" --out photos_dupes.csv --min-size 1024
  py find_dupes.py K:\\ L:\\ --out two_drives.csv     (compare two drives)
  py find_dupes.py J:\\From_K --exclude J:\\From_K\\Old --out a.csv   (skip one folder by full path)
  py find_dupes.py J:\\ --out j.csv --db C:\\dupefinder\\dupefinder.db  (reuse hashes; resumable)
"""

import argparse
import csv
import os
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field

from .common import PARTIAL_BYTES, SKIP_DIRS, fmt, hash_file, walk
from .store import Store

REPORT_COLUMNS = ["group", "copies", "size_bytes", "size_MB", "wasted_MB", "blake2b", "path"]


@dataclass
class Group:
    size: int
    paths: list
    digest: str

    @property
    def wasted(self):
        return self.size * (len(self.paths) - 1)


@dataclass
class ScanResult:
    groups: list = field(default_factory=list)   # list of Group, most wasted space first
    n_files: int = 0                             # files found in stage 1
    n_bytes: int = 0
    candidate_files: int = 0                     # files sharing a size with another (stage 2)
    candidate_bytes: int = 0
    full_hash_bytes: int = 0                     # data hashed in full in stage 4
    cache_hits: int = 0                          # hashes reused from the database
    scan_only: bool = False

    @property
    def wasted(self):
        return sum(g.wasted for g in self.groups)

    @property
    def dup_files(self):
        return sum(len(g.paths) for g in self.groups)


def split_excludes(excludes):
    """--exclude NAME skips every folder with that name;
    --exclude C:\\full\\path skips just that one folder.
    Returns (names, paths), both lower-case."""
    is_path = [n for n in excludes if os.sep in n or ":" in n]
    paths = {os.path.abspath(n).lower().rstrip("\\/") for n in is_path}
    names = {n.lower() for n in excludes if n not in is_path}
    return names, paths


def scan(root, min_size, skip=SKIP_DIRS, skip_paths=()):
    """Yield (path, size) for every regular file under root of at least min_size bytes."""
    for path, size, _ in scan_entries(root, min_size, skip, skip_paths):
        yield path, size


def scan_entries(root, min_size, skip=SKIP_DIRS, skip_paths=()):
    """Like scan, but yields (path, size, modified time in ns) for the hash cache."""
    for entry in walk(root, skip, skip_paths):
        st = entry.stat()
        if st.st_size >= min_size:
            yield entry.path, st.st_size, st.st_mtime_ns


def regroup(groups, key_func, label, log=print):
    """Split every (size, paths) group by key_func(path, size); keep sub-groups of 2+.

    Returns a list of (size, paths, key)."""
    total = sum(len(paths) for _, paths in groups)
    done = 0
    start = time.perf_counter()
    result = []
    for size, paths in groups:
        buckets = defaultdict(list)
        for p in paths:
            key = key_func(p, size)
            done += 1
            if key is not None:
                buckets[key].append(p)
            if log and (done % 500 == 0 or done == total):
                print(f"\r  {label}: {done:,}/{total:,} files", end="", flush=True)
        for key, same in buckets.items():
            if len(same) > 1:
                result.append((size, same, key))
    if log:
        log(f"\r  {label}: {done:,}/{total:,} files in {time.perf_counter() - start:.1f} s")
    return result


def find_duplicates(roots, min_size=1, exclude=(), scan_only=False, log=print, store=None):
    """Run stages 1 to 4 over one or more folders and return a ScanResult.

    `log` receives progress lines; pass None for silence. With `store`
    (a dupefinder.store.Store), hashes of files whose size and modified time
    are unchanged are reused, and new hashes are saved as they are computed."""
    say = log or (lambda *a, **k: None)
    res = ScanResult(scan_only=scan_only)
    t0 = time.perf_counter()

    # Stage 1: scan
    say(f"Stage 1: scanning {', '.join(roots)}")
    by_size = defaultdict(list)
    mtimes = {}
    names, paths_ex = split_excludes(exclude)
    skip = SKIP_DIRS | names
    for path, size, mtime in (f for root in roots for f in scan_entries(root, min_size, skip, paths_ex)):
        by_size[size].append(path)
        mtimes[path] = mtime
        res.n_files += 1
        res.n_bytes += size
        if log and res.n_files % 5000 == 0:
            print(f"\r  {res.n_files:,} files found", end="", flush=True)
    say(f"\r  {res.n_files:,} files, {fmt(res.n_bytes)}, in {time.perf_counter() - t0:.1f} s")

    # Stage 2: keep sizes that occur more than once
    groups = [(s, p) for s, p in by_size.items() if len(p) > 1]
    res.candidate_files = sum(len(p) for _, p in groups)
    res.candidate_bytes = sum(s * len(p) for s, p in groups)
    say(f"Stage 2: {res.candidate_files:,} files ({fmt(res.candidate_bytes)}) share a size "
        f"with another file; {res.n_files - res.candidate_files:,} are unique and dropped")
    if scan_only:
        return res

    if store is None:
        def partial(p, s):
            return hash_file(p, PARTIAL_BYTES)

        def full(p, s):
            return hash_file(p)
    else:
        def partial(p, s):
            return store.hash_with_cache(hash_file, p, s, mtimes[p], "partial", PARTIAL_BYTES)

        def full(p, s):
            return store.hash_with_cache(hash_file, p, s, mtimes[p], "full")
        hits_before = store.hits

    # Stage 3: hash the first 64 KB
    say(f"Stage 3: comparing the first {PARTIAL_BYTES // 1024} KB of each candidate")
    groups = regroup(groups, partial, "partial hash", log)

    # Stage 4: full hash. Files no bigger than 64 KB were already read in
    # full by stage 3, so their partial hash is their full hash.
    small = [g for g in groups if g[0] <= PARTIAL_BYTES]
    big = [(s, p) for s, p, _ in groups if s > PARTIAL_BYTES]
    res.full_hash_bytes = sum(s * len(p) for s, p in big)
    say(f"Stage 4: full hash of {sum(len(p) for _, p in big):,} files "
        f"({fmt(res.full_hash_bytes)})")
    t4 = time.perf_counter()
    final = regroup(big, full, "full hash", log)
    secs = time.perf_counter() - t4
    if store is not None:
        store.commit()
        res.cache_hits = store.hits - hits_before
        say(f"  {res.cache_hits:,} hashes reused from the database")
    elif res.full_hash_bytes and secs > 0:
        say(f"  read speed: {res.full_hash_bytes / 1e6 / secs:,.0f} MB/s")
    final += small

    final.sort(key=lambda g: g[0] * (len(g[1]) - 1), reverse=True)  # most wasted space first
    res.groups = [Group(size, sorted(paths), digest) for size, paths, digest in final]
    return res


def write_report(groups, out):
    """Write groups to a CSV that opens cleanly in Excel (utf-8-sig)."""
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(REPORT_COLUMNS)
        for i, g in enumerate(groups, 1):
            for p in g.paths:
                w.writerow([i, len(g.paths), g.size, round(g.size / 1e6, 3),
                            round(g.wasted / 1e6, 3), g.digest, p])


def main(argv=None):
    ap = argparse.ArgumentParser(description="Read-only duplicate file finder")
    ap.add_argument("roots", nargs="+", metavar="root",
                    help="folder(s) or drive(s) to scan together, e.g. E:\\ F:\\")
    ap.add_argument("--out", default="dupes.csv", help="CSV report to write")
    ap.add_argument("--min-size", type=int, default=1,
                    help="ignore files smaller than this many bytes (default 1 = skip empty files)")
    ap.add_argument("--exclude", action="append", default=[], metavar="NAME",
                    help="skip any folder with this name, e.g. --exclude AppData --exclude OneDrive; "
                         "a full path such as J:\\From_K\\Old skips only that one folder")
    ap.add_argument("--scan-only", action="store_true",
                    help="stop after stage 2 and report how much data stage 4 might read")
    ap.add_argument("--db", metavar="FILE",
                    help="database (e.g. C:\\dupefinder\\dupefinder.db) that remembers hashes, so a "
                         "rescan of unchanged files or a rerun after an interruption is much faster, "
                         "and saves this scan's results")
    args = ap.parse_args(argv)

    roots = [os.path.abspath(r) for r in args.roots]
    out = os.path.abspath(args.out)
    db = os.path.abspath(args.db) if args.db else None
    for root in roots:
        inside = root.lower().rstrip("\\/") + os.sep
        if out.lower().startswith(inside):
            sys.exit("Please write the report outside the folders being scanned.")
        if db and db.lower().startswith(inside):
            sys.exit("Please keep the --db file outside the folders being scanned.")
    t0 = time.perf_counter()
    started = time.strftime("%Y-%m-%d %H:%M:%S")

    store = Store(db) if db else None
    try:
        res = find_duplicates(roots, args.min_size, args.exclude, args.scan_only, store=store)
        if args.scan_only:
            print("--scan-only: stopping here. The size above is the most stage 4 could read.")
            return res
        if store is not None:
            options = {"min_size": args.min_size, "exclude": args.exclude}
            scan_id = store.save_scan(roots, options, res, started)
    except KeyboardInterrupt:
        if store is not None:
            print("\nStopped. Hashes computed so far are saved; run the same command to carry on.")
        raise
    finally:
        if store is not None:
            store.close()

    write_report(res.groups, out)
    print(f"Stage 5: {len(res.groups):,} duplicate groups, {res.dup_files:,} files, "
          f"{fmt(res.wasted)} could be freed by keeping one copy of each")
    print(f"Report: {out}")
    if db:
        print(f"Saved as scan {scan_id} in {db}")
    print(f"Total time: {time.perf_counter() - t0:.1f} s")
    return res


if __name__ == "__main__":
    main()
