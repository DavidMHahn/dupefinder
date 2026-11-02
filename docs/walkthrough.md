# Duplicate file finder: step-by-step walkthrough

Written 30 Oct 2026 for Dave's Windows 11 PC (Ryzen 7 7700X, 32 GB RAM) and a 1.7 TB external USB 3.0 HDD.

Files in this folder:

- `find_dupes.py`: the finished script (read-only; writes only a CSV report)
- `make_test_data.py`: builds a small test folder with known duplicates so you can check the script is right
- `walkthrough.md`: this guide

Both scripts were run here (Linux, Python 3.13) on the generated test data and found exactly the expected 3 groups, 7 files and 10.21 MB of duplicates. They have **not** been run on Windows or on your drive yet; that is what Steps 6 to 8 are for.

---

## Step 0. The idea in one paragraph

Two files can only be identical if they are the same size, so we start with the cheapest information there is (sizes, which come from the directory listing without opening any file) and only read file contents where we can't rule a pair out otherwise. Each stage throws away files that are provably unique, so the expensive stage (reading whole files) runs on as little data as possible.

| Stage | What it does | Cost on an HDD |
|---|---|---|
| 1. Scan | List every file and its size | Directory reads only; usually minutes |
| 2. Size filter | Drop any file whose size is unique | Free (done in RAM) |
| 3. Partial hash | Hash the first 64 KB of each remaining file | One seek + 64 KB per file |
| 4. Full hash | Hash entire files whose first 64 KB still match | Proportional to the GB of real candidates |
| 5. Report | Write groups of identical files to CSV | Free |

**What "hash" means here.** A hash function turns any amount of data into a short fingerprint (here 64 hex characters). Identical data always gives the same fingerprint. With BLAKE2b at 256 bits, the chance of two *different* files producing the same fingerprint by accident is around 1 in 2^128, so in practice equal hashes mean equal contents. (Fact: BLAKE2b is in Python's standard `hashlib`, and is generally faster than SHA-256 in software. On this job the disk, not the hash, will be the bottleneck either way.)

---

## Step 1. Install / check Python

Open **PowerShell** (Start, type "PowerShell", Enter) and run:

```powershell
py --version
```

If you see `Python 3.10` or newer, skip ahead. If you get "not recognized", install it:

```powershell
winget install Python.Python.3.13
```

Then close and reopen PowerShell and run `py --version` again. No extra packages are needed; the script uses only the standard library.

## Step 2. Put the scripts somewhere

```powershell
mkdir C:\dupefinder
cd C:\dupefinder
```

Download `find_dupes.py` and `make_test_data.py` from this project into `C:\dupefinder`.

Keep the report **off** the external drive. The script refuses to write the CSV inside the folder it is scanning, so that it never adds a file to the drive you're checking.

---

## Step 3. Understanding the code, stage by stage

Open `find_dupes.py` in Notepad (or VS Code) and follow along. Each part below matches a commented section in the file.

### 3a. Stage 1: walking the drive (`scan`)

```python
with os.scandir(folder) as entries:
    for entry in entries:
        if entry.is_symlink(): continue
        if entry.is_dir(): stack.append(entry.path)
        elif entry.is_file():
            size = entry.stat().st_size
```

Why `os.scandir`: on Windows, the directory listing that Windows returns already contains each file's size, and Python's `DirEntry.stat()` uses that cached value instead of asking the disk again (this is documented behaviour of `os.scandir` on Windows). On an HDD that saves one extra disk request per file.

Other choices worth knowing:

- **A stack instead of recursion.** Very deep folder trees can't hit Python's recursion limit.
- **Symlinks and junctions are skipped** so the walk can't loop forever or count the same file twice through a link.
- **`$RECYCLE.BIN` and `System Volume Information` are skipped**: they aren't your files and are often access-denied.
- **Errors are reported and skipped**, not fatal. One unreadable folder won't kill a 3-hour run.
- **Empty files are skipped by default** (`--min-size 1`). All empty files are "identical" to each other, which is true but useless.

`scan` is a *generator* (it uses `yield`): it hands back one file at a time, so memory stays small even with hundreds of thousands of files.

### 3b. Stage 2: grouping by size

```python
by_size = defaultdict(list)          # size -> [paths]
...
groups = [(s, p) for s, p in by_size.items() if len(p) > 1]
```

A dictionary keyed by size. Any size with only one file is dropped, since that file can't have a duplicate. On a mixed drive this typically removes most files, especially large media files whose exact byte counts rarely collide by chance (that's an expectation, not something measured on your drive; Step 7 will tell you the real figure).

### 3c. The hash helper (`hash_file`)

```python
with open(path, "rb") as f:          # "rb" = read, binary
    block = f.read(n)
    h.update(block)
```

- `"rb"` opens the file read-only. Python cannot write to a file opened this way. This is the core of why the script is safe.
- Files are read in 1 MB chunks so a 40 GB video never needs 40 GB of RAM.
- With `limit=65536` it stops after the first 64 KB (Stage 3); with no limit it reads the whole file (Stage 4).
- If a file can't be read (in use, bad sector) it returns `None` and that file is simply left out of the results.

### 3d. Stage 3: partial hash, and the `regroup` helper

`regroup` takes each same-size group, splits it into sub-groups by a key (first the 64 KB hash, later the full hash), and keeps only sub-groups with 2 or more files. Two same-size files whose beginnings differ are proven different after reading just 64 KB each.

Why 64 KB? On a spinning disk the expensive part of a small read is the seek (moving the head, roughly 10 ms is a typical figure for 7,200 rpm desktop drives; external drives are often 5,400 rpm and a bit slower). Reading 64 KB instead of 4 KB adds well under a millisecond at 100+ MB/s, but catches more files whose headers are identical (many formats share the first few KB).

### 3e. Stage 4: full hash

Only files that survive Stage 3 get read completely. One shortcut: files of 64 KB or less were already read in full in Stage 3, so the script doesn't read them again. Stage 4 prints the actual **read speed in MB/s**, which is the number you need for the estimate in Step 8.

### 3f. Stage 5: the report

A CSV with one row per file:

| group | copies | size_bytes | size_MB | wasted_MB | blake2b | path |
|---|---|---|---|---|---|---|

- Rows with the same `group` number are identical files.
- `wasted_MB` = size × (copies − 1): the space you'd recover keeping one copy.
- Groups are sorted with the most wasted space first, so the top of the file is where the payoff is.
- It's written as UTF-8 with a BOM (`utf-8-sig`) so Excel shows non-English filenames correctly.

---

## Step 4. Make test data with known answers

```powershell
cd C:\dupefinder
py make_test_data.py C:\dupe_test
```

It creates ~17 MB of random files designed to exercise every stage: real duplicates (3 groups, 7 files), a same-size pair with different starts (should drop at Stage 3), a pair with the same first 64 KB but different endings (should drop at Stage 4), 20 unique files (drop at Stage 2), and two empty files (ignored).

## Step 5. Run on the test data

```powershell
py find_dupes.py C:\dupe_test --out C:\dupefinder\test.csv
```

Expected output (this is what it printed in my test; your times will differ):

```
Stage 1: scanning C:\dupe_test
  31 files, 17.32 MB, in 0.0 s
Stage 2: 11 files (17.15 MB) share a size with another file; 20 are unique and dropped
Stage 3: comparing the first 64 KB of each candidate
  partial hash: 11/11 files in 0.0 s
Stage 4: full hash of 7 files (16.53 MB)
  full hash: 7/7 files in 0.0 s
  read speed: ... MB/s
  small files: 2/2 files in 0.0 s
Stage 5: 3 duplicate groups, 7 files, 10.21 MB could be freed by keeping one copy of each
```

Look at the report:

```powershell
Import-Csv C:\dupefinder\test.csv | Out-GridView
```

(or `start C:\dupefinder\test.csv` to open it in Excel). You should see `video_copy.bin` ×3, `photo.jpg` / `photo (1).jpg`, and `notes.txt` / `notes_backup.txt`, and **not** the `same_size_*` or `same_head_*` files. If that matches, the logic works on your machine. You can delete `C:\dupe_test` afterwards; it's only test data.

> Note: the speed on this test means nothing, because Windows will serve these just-written files from RAM cache. Real speed comes from Step 7.

---

## Step 6. Find the drive letter

Plug in the drive, then:

```powershell
Get-Volume | Where-Object DriveType -eq Removable
Get-PSDrive -PSProvider FileSystem
```

I'll write `E:` below; replace it with your letter. Type the drive root as `E:\` **without quotes** (a quoted `"E:\"` can confuse Windows' argument parsing because `\"` is treated as an escaped quote).

## Step 7. Timed trial on one real folder

Pick a folder on the drive with a few tens of GB of mixed files, for example:

```powershell
py find_dupes.py "E:\SomeFolder" --out C:\dupefinder\trial.csv
```

Write down from the output:

1. Stage 1: number of files and seconds
2. Stage 2: GB that share a size
3. Stage 4: GB fully hashed and the **read speed** in MB/s

## Step 8. Estimate the full run before committing to it

First do a scan-only pass of the whole drive. It reads no file contents, just the directory tree, so it's quick:

```powershell
py find_dupes.py E:\ --scan-only
```

It reports the total files and size, and how many GB share a size with another file. That second number is the **upper bound** for what Stage 4 could read. Then:

- **Stage 4 time (upper bound)** ≈ size-sharing GB ÷ your measured MB/s from Step 7
- **Stage 3 time** ≈ number of candidate files × roughly 10–15 ms each (an estimate for HDD seeks; your Step 7 Stage 3 time ÷ files gives the real per-file figure)

For reference, the absolute worst case of reading every byte of 1.7 TB (calculated, not measured):

```python
tb = 1.7e12
for mbs in (100, 120, 150):
    print(f"{mbs} MB/s: {tb/(mbs*1e6)/3600:.2f} h")
```
```
100 MB/s: 4.72 h
120 MB/s: 3.94 h
150 MB/s: 3.15 h
```

So the earlier "about 3 hours worst case" was a little optimistic: reading the whole drive is about 3 to 5 hours at typical USB 3.0 HDD speeds. The real run should be much less than that, because Stage 2 and Stage 3 avoid reading most of the data, but only your scan-only numbers can say how much less.

## Step 9. The full run

Before starting: set Windows sleep to **Never** temporarily (Settings → System → Power → Screen and sleep), because sleep would suspend the USB drive mid-run.

```powershell
py find_dupes.py E:\ --out C:\dupefinder\dupes.csv
```

To ignore tiny files (thumbnails, `.ini`, etc.) and focus on space that matters:

```powershell
py find_dupes.py E:\ --out C:\dupefinder\dupes.csv --min-size 1048576
```

(1,048,576 bytes = 1 MiB.) If you need to stop, press **Ctrl+C**; nothing on the drive is changed, you just rerun later.

To see the report: `start C:\dupefinder\dupes.csv` in Excel, or `Import-Csv C:\dupefinder\dupes.csv | Out-GridView` (which has a filter box).

---

## Facts vs estimates

**Checked here:** both scripts run on Python 3.13 and produce the correct result on the generated test data, including the tricky same-size and same-first-64-KB cases. The script opens files only with `"rb"` and writes only the CSV.

**Documented behaviour (not tested on your PC):** `os.scandir` on Windows gets file sizes from the directory listing without an extra call per file.

**Estimates:** 100–150 MB/s for a USB 3.0 HDD; ~10–15 ms per small random read; 3–5 h to read the full 1.7 TB. Your Step 7 numbers replace all of these.

## Key assumptions, and what to double-check

1. **"Read-only" means file contents.** The script never modifies, moves or deletes anything. Reading a file *can* update its "last accessed" timestamp if NTFS last-access updates are enabled on your system; I'm not sure how yours is set (`fsutil behavior query disablelastaccess` shows it). Modified and created dates are not touched.
2. **The drive is NTFS or exFAT and is healthy.** If Stage 4's read speed is far below ~80 MB/s, or you see many "cannot read" lines, check the drive's health (e.g. CrystalDiskInfo) before trusting a long run.
3. **Hard links count as duplicates.** If the drive has NTFS hard links (rare on a data drive), two paths to the same physical file will be reported as a duplicate group even though deleting one frees no space.
4. **Duplicates means byte-identical.** The same photo re-saved, resized, or with edited metadata is a different file and won't be found. Finding *similar* images or videos would need a different tool.
5. **The report is for reviewing, not for automatic deletion.** Before deleting anything based on it, check which copy is the one you want to keep (folder, date), and keep a backup of anything important.
6. **Python 3.10+ on Windows**, launched with `py`. Not tested on your PC yet.

---

## Step 10. After reviewing: quarantine, don't delete (added 30 Oct 2026)

`quarantine_dupes.py` reads the report, keeps one copy per group, and **moves** the other copies into a quarantine folder on the same drive, keeping their folder structure. Nothing is deleted. A move on the same drive is instant. Every move is logged, and `--undo` puts everything back.

1. **Dry run (the default; moves nothing):**
   ```powershell
   cd C:\dupefinder
   py quarantine_dupes.py C:\dupefinder\dupes.csv --quarantine J:\_dupes_quarantine
   ```
   Open the `dryrun_....csv` it writes and check the `kept_path` column is the copy you want to keep.
2. **Choosing which copy is kept:** `--keep shortest` (default: the shallowest, shortest path), `oldest`, `newest`, or `alpha`. Add `--prefer "J:\Some\Folder"` to always keep the copy under that folder, and `--only-under "J:\Some\Folder"` to move copies from that folder only.
3. **Real run:** the same command plus `--go` (add `--verify` to re-hash each file just before moving it; this is safer but reads the data again).
4. **Use the drive normally for a while.** If anything is missing: `py quarantine_dupes.py --undo C:\dupefinder\moves_<date>.csv`
5. **Only then** delete `J:\_dupes_quarantine` in Explorer. This is the only step that can't be undone.

Keep the quarantine folder **outside** the folder you scanned, or the next scan will find the quarantined copies as duplicates.

Tested here (Linux, synthetic data): the dry run moved nothing, `--go --verify` moved the 4 expected extra copies, and `--undo` restored the folder exactly (the file listing checksum matched the original).
