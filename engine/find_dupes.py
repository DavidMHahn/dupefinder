"""
find_dupes.py - READ-ONLY duplicate file finder.

It never deletes, moves, renames or writes to the folder it scans.
The only file it creates is the CSV report you name with --out.

Pipeline (each stage only looks at what survived the previous one):
  1. Walk the folder and record every file's size        (no file contents read)
  2. Keep only sizes shared by 2+ files                    (no file contents read)
  3. Hash the first 64 KB of each remaining file           (small read per file)
  4. Fully hash files whose first 64 KB still match        (big reads, only where needed)
  5. Write groups of identical files to a CSV report

Usage (Windows):
  py find_dupes.py E:\\ --out dupes.csv
  py find_dupes.py "E:\\Photos" --out photos_dupes.csv --min-size 1024
  py find_dupes.py K:\\ L:\\ --out two_drives.csv     (compare two drives)
  py find_dupes.py J:\\From_K --exclude J:\\From_K\\Old --out a.csv   (skip one folder by full path)
"""

import argparse
import csv
import hashlib
import os
import sys
import time
from collections import defaultdict

PARTIAL_BYTES = 64 * 1024      # stage 3 reads this much from the start of each file
CHUNK_BYTES = 1024 * 1024      # stage 4 reads files in 1 MB chunks

# Windows system folders on the root of a drive that are not your files.
SKIP_DIRS = {"$recycle.bin", "system volume information"}   # compared lower-case


def fmt(n):
    """Human-readable size: 1234567 -> '1.23 MB'."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1000 or unit == "TB":
            return f"{n:,.2f} {unit}" if unit != "B" else f"{n} B"
        n /= 1000


# ---------------------------------------------------------------- stage 1
def scan(root, min_size, skip=SKIP_DIRS, skip_paths=()):
    """Yield (path, size) for every regular file under root.

    os.scandir is used instead of os.walk + os.path.getsize because on
    Windows the directory listing already contains each file's size,
    so we do not need a separate request to the disk per file.
    """
    stack = [root]
    while stack:
        folder = stack.pop()
        try:
            with os.scandir(folder) as entries:
                for entry in entries:
                    try:
                        if entry.is_symlink() or getattr(entry, "is_junction", bool)():
                            continue                  # don't follow links/junctions
                        if entry.is_dir():
                            if (entry.name.lower() not in skip
                                    and os.path.abspath(entry.path).lower() not in skip_paths):
                                stack.append(entry.path)
                        elif entry.is_file():
                            size = entry.stat().st_size
                            if size >= min_size:
                                yield entry.path, size
                    except OSError as e:
                        print(f"  skipped {entry.path}: {e}", file=sys.stderr)
        except OSError as e:
            print(f"  cannot open folder {folder}: {e}", file=sys.stderr)


# ---------------------------------------------------------------- hashing
def hash_file(path, limit=None):
    """Return the BLAKE2b hex digest of a file, or of its first `limit` bytes.

    The file is opened with "rb" (read binary), which cannot modify it.
    Returns None if the file cannot be read (locked, removed, bad sector).
    """
    h = hashlib.blake2b(digest_size=32)
    remaining = limit
    try:
        with open(path, "rb") as f:
            while True:
                n = CHUNK_BYTES if remaining is None else min(CHUNK_BYTES, remaining)
                if n == 0:
                    break
                block = f.read(n)
                if not block:
                    break
                h.update(block)
                if remaining is not None:
                    remaining -= len(block)
    except OSError as e:
        print(f"  cannot read {path}: {e}", file=sys.stderr)
        return None
    return h.hexdigest()


def regroup(groups, key_func, label):
    """Split every group by key_func(path) and keep only sub-groups of 2+.

    groups is a list of (size, [paths]). Prints progress and timing.
    """
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
            if done % 500 == 0 or done == total:
                print(f"\r  {label}: {done:,}/{total:,} files", end="", flush=True)
        for key, same in buckets.items():
            if len(same) > 1:
                result.append((size, same, key))
    print(f"\r  {label}: {done:,}/{total:,} files in {time.perf_counter() - start:.1f} s")
    return result


# ---------------------------------------------------------------- main
def main():
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
    args = ap.parse_args()

    roots = [os.path.abspath(r) for r in args.roots]
    out = os.path.abspath(args.out)
    for root in roots:
        if out.lower().startswith(root.lower().rstrip("\\/") + os.sep):
            sys.exit("Please write the report outside the folders being scanned.")
    t0 = time.perf_counter()

    # Stage 1: scan
    print(f"Stage 1: scanning {', '.join(roots)}")
    by_size = defaultdict(list)
    n_files = n_bytes = 0
    # --exclude NAME skips every folder with that name; --exclude C:\\full\\path skips just that folder
    paths_ex = {os.path.abspath(n).lower().rstrip("\\/") for n in args.exclude if os.sep in n or ":" in n}
    skip = SKIP_DIRS | {n.lower() for n in args.exclude if not (os.sep in n or ":" in n)}
    for path, size in (f for root in roots for f in scan(root, args.min_size, skip, paths_ex)):
        by_size[size].append(path)
        n_files += 1
        n_bytes += size
        if n_files % 5000 == 0:
            print(f"\r  {n_files:,} files found", end="", flush=True)
    print(f"\r  {n_files:,} files, {fmt(n_bytes)}, "
          f"in {time.perf_counter() - t0:.1f} s")

    # Stage 2: keep sizes that occur more than once
    groups = [(s, p) for s, p in by_size.items() if len(p) > 1]
    cand_files = sum(len(p) for _, p in groups)
    cand_bytes = sum(s * len(p) for s, p in groups)
    print(f"Stage 2: {cand_files:,} files ({fmt(cand_bytes)}) share a size "
          f"with another file; {n_files - cand_files:,} are unique and dropped")
    if args.scan_only:
        print("--scan-only: stopping here. The size above is the most stage 4 could read.")
        return

    # Stage 3: hash the first 64 KB
    print(f"Stage 3: comparing the first {PARTIAL_BYTES // 1024} KB of each candidate")
    groups = regroup(groups, lambda p, s: hash_file(p, PARTIAL_BYTES), "partial hash")

    # Stage 4: full hash. Files no bigger than 64 KB were already read in
    # full by stage 3, so their partial hash is their full hash.
    small = [g for g in groups if g[0] <= PARTIAL_BYTES]
    big = [(s, p) for s, p, _ in groups if s > PARTIAL_BYTES]
    big_bytes = sum(s * len(p) for s, p in big)
    print(f"Stage 4: full hash of {sum(len(p) for _, p in big):,} files "
          f"({fmt(big_bytes)})")
    t4 = time.perf_counter()
    final = regroup(big, lambda p, s: hash_file(p), "full hash")
    secs = time.perf_counter() - t4
    if big_bytes and secs > 0:
        print(f"  read speed: {big_bytes / 1e6 / secs:,.0f} MB/s")
    final += small

    # Stage 5: report
    final.sort(key=lambda g: g[0] * (len(g[1]) - 1), reverse=True)  # most wasted space first
    wasted = 0
    with open(out, "w", newline="", encoding="utf-8-sig") as f:   # utf-8-sig opens cleanly in Excel
        w = csv.writer(f)
        w.writerow(["group", "copies", "size_bytes", "size_MB", "wasted_MB", "blake2b", "path"])
        for i, (size, paths, digest) in enumerate(final, 1):
            waste = size * (len(paths) - 1)
            wasted += waste
            for p in sorted(paths):
                w.writerow([i, len(paths), size, round(size / 1e6, 3),
                            round(waste / 1e6, 3), digest, p])
    print(f"Stage 5: {len(final):,} duplicate groups, "
          f"{sum(len(p) for _, p, _ in final):,} files, "
          f"{fmt(wasted)} could be freed by keeping one copy of each")
    print(f"Report: {out}")
    print(f"Total time: {time.perf_counter() - t0:.1f} s")


if __name__ == "__main__":
    main()
