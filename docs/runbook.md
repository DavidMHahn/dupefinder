# Duplicate file cleanup runbook

Nov 1, 2026 · @Dave

## Overview

Nothing in this process deletes a file. The only irreversible step is when you delete the quarantine folder yourself at the end, after the checks below have passed.

| Script | What it does | Changes files? |
| --- | --- | --- |
| `find_dupes.py` | Scans a folder, finds byte-identical files (size, then first 64 KB, then full BLAKE2b hash) and writes a CSV report | No. It only reads, and writes the CSV outside the scanned folder |
| `make_test_data.py` | Builds a throwaway folder with known duplicates (3 groups, 7 files, 10.21 MB) | Creates new test files only |
| `quarantine_dupes.py` | Reads the CSV, keeps one copy per group and moves the extras to a quarantine folder on the same drive | Dry run by default; moves only with `--go`; `--undo` reverses |
| `verify_quarantine.py` | Before you delete the quarantine, checks every kept file still exists and is identical to its quarantined copy | No. It only reads |
| `compare_backup_sets.py` | Compares backup sets inside one backup folder and lists files in an old set that have no identical copy in the sets you keep (at\_risk.csv) | No. It only reads |
| `rescue_files.py` | Moves the at-risk files out of an old backup set into a plain folder on the same drive, before that set is deleted | Dry run by default; moves only with `--go`; `--undo` reverses |

All six live in `C:\dupefinder`. Download them from the project's `dupe-finder` folder.

**Rules that protect your data:**

- Run on the original files, never inside a backup folder (Seagate Toolkit on J:, Smart Switch, File History). Backup tools expect their own layout.
- Always dry run first, and read the `kept_path` column before adding `--go`.
- Use `--go --verify`, so every file is re-hashed just before it moves.
- Keep every `moves_*.csv` log until the quarantine is deleted. It is the undo record.
- Exclude `AppData` and `OneDrive`, and leave program folders (drivers, NinjaTrader, `.cache`) alone.
- In music folders, add `--skip-name Folder.jpg --skip-name "AlbumArt*" --skip-name desktop.ini`. Album art is often identical across albums but belongs in each folder.
- To skip one specific folder, give `--exclude` its full path (`--exclude J:\From_K\Old`). A bare name skips every folder with that name, anywhere.

## Setup and test rehearsal

Do this once, and again whenever you download a new version of a script. The rehearsal checks the whole process on throwaway files, so a mistake costs nothing. Every command runs in PowerShell.

1. Check Python (3.10 or newer) and go to the scripts folder:

   ```powershell
   py --version
   cd C:\dupefinder
   ```
2. Check you have the latest scripts. Each command should print matching lines:

   ```powershell
   Select-String -Path find_dupes.py -Pattern "skip_paths", "is_junction"
   Select-String -Path quarantine_dupes.py -Pattern "skip_name", "already back in place"
   Select-String -Path verify_quarantine.py -Pattern "Problem summary"
   ```
3. Build the test data. The expected result is printed at the end:

   ```powershell
   py make_test_data.py C:\dupefinder\dupe_test
   ```
4. Find the duplicates. The expected result is `Stage 5: 3 duplicate groups, 7 files, 10.21 MB`:

   ```powershell
   py find_dupes.py C:\dupefinder\dupe_test --out C:\dupefinder\test.csv
   ```
5. Dry run. It uses a separate test quarantine folder, so it can never mix with real quarantined files. The expected result is `Would move 4 files`, keeping every copy in `dupe_test\a\`:

   ```powershell
   py quarantine_dupes.py C:\dupefinder\test.csv --quarantine C:\_test_quarantine
   ```
6. Real move, then verify. The expected results are `Moved 4 files`, then `SAFE: every quarantined file has an identical kept copy.`:

   ```powershell
   py quarantine_dupes.py C:\dupefinder\test.csv --quarantine C:\_test_quarantine --go --verify
   $log = (Get-ChildItem C:\dupefinder\moves_*.csv | Sort-Object LastWriteTime | Select-Object -Last 1).FullName
   py verify_quarantine.py $log
   ```
7. Undo, and count the files. The expected results are `Restored 4 of 4 files` and a count of 33 (31 files plus 2 empty ones):

   ```powershell
   py quarantine_dupes.py --undo $log
   (Get-ChildItem C:\dupefinder\dupe_test -Recurse -File).Count
   ```
8. Clean up only the test folders. Never type `C:\_dupes_quarantine` here, because that folder holds your real quarantined files:

   ```powershell
   Remove-Item C:\dupefinder\dupe_test, C:\_test_quarantine -Recurse
   mkdir C:\dupefinder\archive -Force
   Move-Item C:\dupefinder\moves_*.csv, C:\dupefinder\dryrun_*.csv C:\dupefinder\archive
   ```

If any step's output differs from what's expected, stop and don't run on real files.

## Runbook for real files

Seven steps. Steps 1 to 6 can be undone at any time. Only step 7 is permanent. The example uses your user folder. For another folder or drive, change the path, and keep the quarantine on that same drive.

1. **Before you start:** make sure Toolkit's last backup of the PC succeeded. Then scan, writing the report with today's date. This step is read-only:

   ```powershell
   cd C:\dupefinder
   $d = Get-Date -Format yyyyMMdd
   py find_dupes.py C:\Users\hahnd --out C:\dupefinder\scan_$d.csv --exclude AppData --exclude OneDrive --min-size 1048576
   ```
2. **Review the report.** Decide which folder's copies you keep and which folder's copies go. Biggest savings are at the top:

   ```powershell
   Import-Csv C:\dupefinder\scan_$d.csv | Out-GridView
   ```

   Look for pairs of folders (for example `Pics Vids` vs `8668 Menkar Docs\PicsVids`). Skip program, driver and app-data folders. Open any files with the same content but different names before deciding, because one may be a mis-saved document.
3. **Dry run** with the keep folder and the discard folder you chose:

   ```powershell
   py quarantine_dupes.py C:\dupefinder\scan_$d.csv --quarantine C:\_dupes_quarantine --prefer "<KEEP folder>" --only-under "<DISCARD folder>"
   ```
4. **Check the dry run.** Every `would move` row should come from the discard folder, and every `kept_path` should be in the keep folder:

   ```powershell
   $dry = (Get-ChildItem C:\dupefinder\dryrun_*.csv | Sort-Object LastWriteTime | Select-Object -Last 1).FullName
   Import-Csv $dry | Group-Object status | Select-Object Count, Name
   Import-Csv $dry | Where-Object status -eq "would move" | Select-Object kept_path, original_path | Out-GridView
   ```
5. **Move, then verify straight away.** Repeat the exact dry-run command with `--go --verify` added:

   ```powershell
   py quarantine_dupes.py C:\dupefinder\scan_$d.csv --quarantine C:\_dupes_quarantine --prefer "<KEEP folder>" --only-under "<DISCARD folder>" --go --verify
   $log = (Get-ChildItem C:\dupefinder\moves_*.csv | Sort-Object LastWriteTime | Select-Object -Last 1).FullName
   py verify_quarantine.py $log
   ```

   It should print `SAFE`. If it doesn't, run `py quarantine_dupes.py --undo $log`.
6. **Live with it for one to two weeks.** Open some of the kept files. If anything is missing, `py quarantine_dupes.py --undo <that moves log>` puts it back.
7. **Delete the quarantine (permanent).** First run `verify_quarantine.py` again on **every** `moves_*.csv` from this round. All of them must print `SAFE`:

   ```powershell
   Get-ChildItem C:\dupefinder\moves_*.csv | ForEach-Object { py verify_quarantine.py $_.FullName }
   Remove-Item C:\_dupes_quarantine -Recurse
   ```

   `Remove-Item` skips the Recycle Bin. If you'd like one more safety net, delete the folder in Explorer instead. Then move the old `moves_*.csv` logs into an `archive` subfolder, so the next round starts clean.

   A verify run *after* the delete prints `quarantined copy missing` for every file and ends `NOT SAFE`. That is expected, because there is nothing left to compare. Only a `KEPT COPY` line would mean a problem.

## Comparing, merging and backing up drives

The same scripts work across several drives, and robocopy does the copying. This is the order used for J: and K: in November 2026. Steps 2 and 5 need an **Administrator** PowerShell window when the drive holds Windows Backup folders (they need `/B`).

1. **Clean each drive on its own first** with the runbook above, keeping each drive's quarantine on that drive.
2. **Merge by copying, never moving**, the older drive into a folder on the big one. Preview with `/L`, then run it again without `/L /NFL /NDL` and with `/LOG:C:\dupefinder\merge.txt /TEE`:

   ```powershell
   robocopy K:\ J:\From_K /E /B /XJ /COPY:DAT /DCOPY:T /R:1 /W:1 /XD 'K:\$RECYCLE.BIN' 'K:\System Volume Information' 'K:\_dupes_quarantine' /L /NFL /NDL /LOG:C:\dupefinder\merge_preview.txt
   ```

   Copying from a drive root marks the new folder hidden. Afterwards, run `attrib -s -h J:\From_K` (the folder only, without `/s /d`).
3. **Scan the merged archive** together with other plain folders on that drive. Leave out backup-tool folders, and skip Windows Backup sets by full path:

   ```powershell
   py find_dupes.py J:\From_K J:\Rescued_H8P3IB1 --exclude J:\From_K\DESKTOP-H8P3IB1 --out C:\dupefinder\archive_dupes.csv
   ```
4. **Quarantine in batches** with `--only-under`, the biggest and clearest batch first. The kept copy is chosen from outside that folder whenever one exists. Every batch runs dry run, then `--go --verify`, then `verify_quarantine.py`. All batches can reuse the same report.
5. **Make the older drive an exact backup** of the cleaned archive. First verify and delete that drive's own quarantine. Then preview the mirror:

   ```powershell
   robocopy J:\From_K K:\ /MIR /B /XJ /COPY:DAT /DCOPY:T /R:1 /W:1 /XD '$RECYCLE.BIN' 'System Volume Information' '_dupes_quarantine' 'Rescued_H8P3IB1' /L /NFL /NDL /LOG:C:\dupefinder\backup_preview.txt
   ```

   The **Extras** files are what the real run deletes from the backup drive. They must equal the files you quarantined on the archive. Run it for real without `/L /NFL /NDL`, then preview once more: Extras should be 0 files. Copy any other folders across with `robocopy <source> <dest> /E /COPY:DAT /DCOPY:T /R:1 /W:1`.

**Things that tripped us up:**

- In PowerShell, put any path containing `$` in single quotes. In double quotes, `$RECYCLE` is read as a variable.
- Robocopy's `g` is binary gigabytes. Multiply by 1.074 for normal GB (823.452 g = 884.2 GB).
- `/MIR` at a drive root listed 2 extra folders even after the real run. They are most likely the drive's own Recycle Bin and System Volume Information, which are excluded and so never deleted.
- Robocopy treats files as identical by size and date, not by content. Drive-to-drive copies ran at about 24 MB/s for mixed files and 80 MB/s for large videos.
- Piping a verify run into `Select-String` used to crash on file names with special characters. `verify_quarantine.py` now prints a **Problem summary** instead, so no pipe is needed.

## Safety checklist

Tick these off for each round, before the step they guard.

- [ ] Rehearsal on test data passed with the current versions of the scripts
- [ ] Toolkit's last backup of the PC succeeded (your copy of last resort)
- [ ] The scanned folder is your own files, not a backup or program folder
- [ ] The report is written outside the scanned folder, and the quarantine is on the same drive but outside it
- [ ] Dry run read: every `would move` row is in the discard folder, every `kept_path` is in the keep folder
- [ ] `--go` was run with `--verify`
- [ ] `verify_quarantine.py` printed `SAFE` right after the move
- [ ] One to two weeks passed with nothing missing
- [ ] `verify_quarantine.py` printed `SAFE` again for every moves log, just before deleting

**Never:**

- Run `--go` on anything inside `J:\Toolkit\Backup`, a Smart Switch backup, or another backup tool's folder.
- Run `--go` on a report more than a day old. Files may have changed since, so rescan first (about 90 s for your user folder).
- Delete a `moves_*.csv` log while its quarantine folder exists. Logs moved into `archive` still work with `--undo` and `verify_quarantine.py`.
- Delete `C:\_dupes_quarantine` while any verify run says `NOT SAFE`.
- Empty the Recycle Bin straight after deleting the quarantine. Give it a few more days.
- Run `robocopy /MIR` without a `/L` preview first, or with the source and destination the wrong way round. `/MIR` deletes from the destination.

If something goes wrong: stop, don't delete anything, and run `py quarantine_dupes.py --undo <moves log>`. If a kept file itself is lost, restore it from the Toolkit backup on J:.

## Appendix: script source

These are the current versions (1 Nov 2026). Each was tested on Linux with the test data, and `find_dupes.py` and `quarantine_dupes.py` were also confirmed on your PC. If your copy differs, download it again from the project's `dupe-finder` folder.

### find\_dupes.py (read-only finder)

```python
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
```

### quarantine\_dupes.py (dry run, move, undo)

```python
"""
quarantine_dupes.py - act on the CSV from find_dupes.py, SAFELY.

It never deletes anything. For each duplicate group it keeps one copy
(chosen by --keep) and MOVES the others into a quarantine folder on the
same drive, keeping their original folder structure. A move within one
drive is instant (no data is copied). Every move is logged, and --undo
puts everything back.

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
import hashlib
import os
import sys
import time
from collections import defaultdict


def blake2b(path):
    h = hashlib.blake2b(digest_size=32)
    with open(path, "rb") as f:
        while block := f.read(1024 * 1024):
            h.update(block)
    return h.hexdigest()


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


def under(path, folders):
    """True if path is inside any of folders (case-insensitive)."""
    p = path.lower()
    return any(p.startswith(f.lower().rstrip("\\/") + os.sep) for f in folders)


def quarantine_path(qroot, path):
    """J:\\Photos\\a.jpg -> J:\\_dupes_quarantine\\Photos\\a.jpg"""
    drive, rest = os.path.splitdrive(os.path.abspath(path))
    return os.path.join(qroot, rest.lstrip("\\/"))


def undo(log_path):
    with open(log_path, newline="", encoding="utf-8-sig") as f:
        rows = [r for r in csv.DictReader(f) if r["status"] == "moved"]
    back = 0
    for r in rows:
        src, dst = r["quarantine_path"], r["original_path"]
        if not os.path.exists(src) and os.path.exists(dst):
            print(f"  already back in place: {dst}")
        elif not os.path.exists(src):
            print(f"  missing in quarantine, skipped: {src}")
        elif os.path.exists(dst):
            print(f"  something already at original path, skipped: {dst}")
        else:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            os.rename(src, dst)
            back += 1
    print(f"Restored {back:,} of {len(rows):,} files.")


def main():
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
    args = ap.parse_args()

    if args.undo:
        return undo(args.undo)
    if not args.report or not args.quarantine:
        ap.error("report and --quarantine are required")

    qroot = os.path.abspath(args.quarantine)

    groups = defaultdict(list)
    meta = {}
    with open(args.report, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if under(row["path"], [qroot]):
                continue          # never keep, or move, a file already in quarantine
            name = os.path.basename(row["path"]).lower()
            if any(fnmatch.fnmatch(name, pat.lower()) for pat in args.skip_name):
                continue          # e.g. album art / desktop.ini that belongs in its folder
            groups[row["group"]].append(row["path"])
            meta[row["group"]] = (int(row["size_bytes"]), row["blake2b"])

    qdrive = os.path.splitdrive(qroot)[0].lower()

    mode = "MOVING FILES" if args.go else "DRY RUN (nothing will be moved; add --go to move)"
    print(mode)
    log_path = os.path.abspath(
        f"{'moves' if args.go else 'dryrun'}_{time.strftime('%Y%m%d_%H%M%S')}.csv")
    moved = skipped = freed = 0

    with open(log_path, "w", newline="", encoding="utf-8-sig") as logf:
        log = csv.writer(logf)
        log.writerow(["group", "status", "kept_path", "original_path", "quarantine_path", "size_bytes"])
        for g, paths in groups.items():
            size, digest = meta[g]
            existing = [p for p in paths if os.path.isfile(p) and os.path.getsize(p) == size]
            if len(existing) < 2:
                skipped += len(paths) - 1
                log.writerow([g, "skipped: fewer than 2 copies still present", "", "", "", size])
                continue
            outside = [p for p in existing if not under(p, args.only_under)]
            keeper = choose_keeper(outside or existing, args.keep, args.prefer)
            for p in existing:
                if p == keeper:
                    continue
                if args.only_under and not under(p, args.only_under):
                    log.writerow([g, "skipped: outside --only-under", keeper, p, "", size])
                    skipped += 1
                    continue
                if os.path.splitdrive(p)[0].lower() != qdrive:
                    # moving across drives would copy data; quarantine stays on one drive
                    log.writerow([g, "skipped: on a different drive than --quarantine", keeper, p, "", size])
                    skipped += 1
                    continue
                dest = quarantine_path(qroot, p)
                status = "would move"
                if args.go:
                    if args.verify and not (blake2b(p) == blake2b(keeper) == digest):
                        log.writerow([g, "skipped: contents changed since report", keeper, p, "", size])
                        skipped += 1
                        continue
                    if os.path.exists(dest):
                        log.writerow([g, "skipped: already in quarantine", keeper, p, dest, size])
                        skipped += 1
                        continue
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    os.rename(p, dest)
                    status = "moved"
                log.writerow([g, status, keeper, p, dest, size])
                moved += 1
                freed += size

    verb = "Moved" if args.go else "Would move"
    print(f"{verb} {moved:,} files ({freed / 1e9:,.2f} GB); skipped {skipped:,}.")
    print(f"Log: {log_path}")
    if args.go:
        print(f"To undo: py quarantine_dupes.py --undo \"{log_path}\"")


if __name__ == "__main__":
    main()
```

### verify\_quarantine.py (read-only check before deleting)

Tested here: it prints `SAFE` for a clean quarantine, and `NOT SAFE` (exit code 1) when a kept file has been changed or deleted.

```python
"""
verify_quarantine.py - READ-ONLY check to run BEFORE you delete a quarantine folder.

For every file a moves log says was quarantined, it confirms:
  1. the kept copy still exists at kept_path
  2. the quarantined copy still exists at quarantine_path
  3. both have the same size and the same BLAKE2b hash
  4. nothing was put back at original_path since (if it was, it is reported)

Only when every row passes is it safe to delete the quarantine folder.

  py verify_quarantine.py C:\\dupefinder\\moves_20261030_175000.csv
"""

import csv
import hashlib
import os
import sys


def blake2b(path):
    h = hashlib.blake2b(digest_size=32)
    with open(path, "rb") as f:
        while block := f.read(1024 * 1024):
            h.update(block)
    return h.hexdigest()


def main():
    # file names with characters the console can't show must not crash the check
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    if len(sys.argv) != 2:
        sys.exit("usage: py verify_quarantine.py <moves_log.csv>")
    with open(sys.argv[1], newline="", encoding="utf-8-sig") as f:
        rows = [r for r in csv.DictReader(f) if r["status"] == "moved"]

    ok = 0
    problems = []
    for r in rows:
        kept, quar, orig = r["kept_path"], r["quarantine_path"], r["original_path"]
        if not os.path.isfile(kept):
            problems.append(f"KEPT COPY MISSING: {kept}  (do not delete {quar})")
        elif not os.path.isfile(quar):
            if os.path.isfile(orig):
                problems.append(f"already restored to original place: {orig}")
            else:
                problems.append(f"quarantined copy missing: {quar}")
        elif os.path.getsize(kept) != os.path.getsize(quar) or blake2b(kept) != blake2b(quar):
            problems.append(f"KEPT COPY CHANGED, no longer identical: {kept}  (do not delete {quar})")
        else:
            ok += 1

    for p in problems:
        print("  " + p)
    kinds = {}
    for p in problems:
        k = p.split(":", 1)[0]
        kinds[k] = kinds.get(k, 0) + 1
    if kinds:
        print("Problem summary:")
        for k, n in sorted(kinds.items()):
            print(f"  {n:,}  {k}")
    print(f"{ok:,} of {len(rows):,} quarantined files verified: kept copy present and identical.")
    if ok == len(rows):
        print("SAFE: every quarantined file has an identical kept copy.")
    else:
        print("NOT SAFE to delete the whole quarantine folder. Review the lines above first.")
        sys.exit(1)


if __name__ == "__main__":
    main()
```

### make\_test\_data.py (rehearsal data)

```python
"""
make_test_data.py - build a small folder with KNOWN duplicates, so you can
check that find_dupes.py finds exactly what it should.

  py make_test_data.py C:\\dupe_test

Creates (all random bytes):
  3 copies of a 5 MB file                   -> 1 group, 10 MB wasted
  2 copies of a 200 KB file                 -> 1 group, 0.2 MB wasted
  2 copies of a 10 KB file                  -> 1 group, 0.01 MB wasted
  2 files of the same size, different start -> NOT duplicates (dropped at stage 3)
  2 files of the same size and same first
    64 KB but different endings             -> NOT duplicates (dropped at stage 4)
  20 unique files of different sizes        -> NOT duplicates (dropped at stage 2)
  1 empty file copied twice                 -> ignored (empty files are skipped)
"""

import os
import random
import sys

root = sys.argv[1] if len(sys.argv) > 1 else "dupe_test"
if os.path.exists(root) and os.listdir(root):
    sys.exit(f"{root} already exists and is not empty; pick a new folder name.")
os.makedirs(root, exist_ok=True)
rng = random.Random(42)


def write(rel, data):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


big = rng.randbytes(5_000_000)
for d in ("a", "b", "c/deep"):
    write(f"{d}/video_copy.bin", big)

mid = rng.randbytes(200_000)
write("a/photo.jpg", mid)
write("b/photo (1).jpg", mid)

small = rng.randbytes(10_000)
write("a/notes.txt", small)
write("c/notes_backup.txt", small)

write("a/same_size_1.bin", rng.randbytes(300_000))
write("b/same_size_2.bin", rng.randbytes(300_000))

head = rng.randbytes(64 * 1024)
write("a/same_head_1.bin", head + rng.randbytes(500_000))
write("b/same_head_2.bin", head + rng.randbytes(500_000))

for i in range(20):
    write(f"unique/file_{i}.bin", rng.randbytes(1000 + i * 777))

write("a/empty.txt", b"")
write("b/empty.txt", b"")

print(f"Test data written to {os.path.abspath(root)}")
print("Expected: 3 duplicate groups, 7 files, about 10.21 MB wasted.")
```

### compare\_backup\_sets.py

Used on 31 Oct 2026 to find the 290 GB in the old Toolkit set that existed nowhere else. Read-only.

```python
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
```

### rescue\_files.py

Used on 31 Oct 2026 to move 3,887 at-risk files (127.92 GB) into `J:\Rescued_H8P3IB1`. Dry run by default.

```python
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
```
