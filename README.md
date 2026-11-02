# dupefinder

Finds duplicate files on a drive, guides you through the detection, analysis, quarantine, and deletion of duplicate files.

This repository holds the command-line toolkit that cleaned up about 563 GB of duplicates across three Windows drives (Oct 30 to Nov 1, 2026), and is the starting point for a user-friendly desktop app.

## The rule

Nothing is deleted until a verified quarantine has waited. Scanning is read-only, moves are dry runs by default, every move is logged and can be undone, and a verify step must say SAFE before you delete a quarantine folder by hand.

## What's here

| Path | What it is |
|---|---|
| `dupefinder/` | The engine as a Python package: `finder`, `quarantine`, `verify`, `backup_sets`, `rescue`, `testdata`, `review` (groups results by folder), `keepers` (decides which copy of each group stays), `dryrun` (checks every planned move without moving anything), `mover` (carries out a saved dry run), `deleter` (the only code that deletes, with the conditions for it), and `store` (the SQLite database the app keeps its work in). Each has functions a UI can call and a `main()` for the command line. |
| `dupefinder/app/` | The desktop app. All eight steps work, from Scan to Delete are shown but not built yet. |
| `tests/` | Automated tests, including the edge cases found on real drives. They run on Windows and Linux for every pull request. |
| `engine/find_dupes.py` | Read-only scan of one or more folders or drives: size, then first 64 KB, then full BLAKE2b hash. Writes a CSV report. |
| `engine/quarantine_dupes.py` | Moves extra copies to a quarantine folder on the same drive. Dry run by default; `--go` to move, `--verify` to re-hash first, `--undo LOG` to restore. Keeper rules: `--only-under`, `--prefer`, `--skip-name`. |
| `engine/verify_quarantine.py` | Read-only check of a moves log: SAFE or NOT SAFE, with a problem summary. |
| `engine/compare_backup_sets.py` | Read-only: lists files in an old backup set that have no identical copy in the sets you keep. |
| `engine/rescue_files.py` | Moves those at-risk files out of the old set before it is deleted (dry run, `--go`, `--undo`). |
| `engine/make_test_data.py` | Builds a throwaway folder with known duplicates (3 groups, 7 files, 10.21 MB) for rehearsals and tests. |
| `docs/runbook.md` | Step-by-step runbook with every command, gotchas, and the scripts as they were used. |
| `docs/walkthrough.md` | First-time walkthrough on test data. |
| `docs/app-idea-notes.md` | Notes for the standalone app. The full product brief is a separate document. |

The `engine/` scripts are now small wrappers around the package, with the same options as before. They need the `dupefinder/` folder next to `engine/`, so copy the whole repository rather than a single script.

## Quick start (Windows, Python 3.9+)

```powershell
py engine\make_test_data.py C:\dupetest
py engine\find_dupes.py C:\dupetest --out C:\dupefinder\test.csv
py engine\quarantine_dupes.py C:\dupefinder\test.csv              # dry run, changes nothing
py engine\quarantine_dupes.py C:\dupefinder\test.csv --go --verify
py engine\verify_quarantine.py <moves log printed above>
```

Add `--db C:\dupefinder\dupefinder.db` to `find_dupes.py` to remember hashes in a small database outside the scanned drive. A rescan then only reads files that are new or changed, and if a scan is interrupted, running the same command again carries on where it stopped. Each scan's results are saved in the database too.

Never run the tools inside live backup folders (Seagate Toolkit, Samsung Smart Switch, File History, Windows Backup).

## The desktop app

Needs Python 3.10 or newer.

```powershell
py -m pip install -r requirements-app.txt
py -m dupefinder.app
```

Add one or more drives or folders, optionally folders to skip, and click **Start scan**. Scanning only reads files. Results are saved in `%LOCALAPPDATA%\dupefinder\dupefinder.db`, so scanning the same drive again only reads new or changed files, and a stopped scan carries on where it stopped. **Save report as CSV** writes the same report as `find_dupes.py`.

**Review groups** shows a scan's duplicates gathered by the folders that hold the copies, biggest saving first, with the identical files of each folder set below. You can filter by folder or file name, reopen any earlier scan, and open a file's folder in File Explorer. Nothing on this screen changes a file.

**Choose keepers** decides which copy of each group stays. Pick the rule (shortest path, oldest, newest or alphabetical), optionally list folders whose copies you want to keep first, folders to clean up (copies elsewhere are never moved), and file names that never move (album art, `desktop.ini` and similar are listed by default). Double-click any copy to keep it instead; **Use the rules for this group** undoes that. The total that would be freed updates as you go, and your choices are saved with the scan, so you can leave and come back. Nothing on this screen moves a file either.

**Dry run** previews every move. Each drive gets a quarantine folder (by default `_dupes_quarantine` at the top of the drive; you can change it, but it must be on the same drive so moves are instant). It checks each copy exactly as the Quarantine step will: the copy and its kept copy are still there and unchanged in size, the copy is not inside a backup program's folder (File History, Windows Backup, Smart Switch, Seagate Toolkit, Time Machine), it is on the same drive as its quarantine folder, and nothing is already at its quarantine path. The result is saved, and **Save the plan as CSV** writes it in the same format as `quarantine_dupes.py`'s dry run log. Nothing is moved.

**Quarantine** is the first step that changes files. It carries out the saved dry run and nothing else (if you change a keeper choice, it asks for a new dry run). It asks before starting, checks each copy again just before moving it (and, by default, re-reads both files to confirm they are still identical), and moves it into the quarantine folder; nothing is deleted. Every move is written to a moves log as it happens, in `%LOCALAPPDATA%\dupefinder\logs`, in the same format as `quarantine_dupes.py`, so `verify_quarantine.py` works on it too. **Stop** stops between two files, and **Put everything back** undoes the whole run, even after closing the app.

**Verify** re-reads every quarantined copy and its kept copy and says **SAFE** only if every one is still identical, the same check as `verify_quarantine.py`. Otherwise it says **NOT SAFE to delete** and lists each problem (kept copy missing or changed, quarantined copy missing, already put back, or a file that could not be read). It only reads files, can be stopped, and remembers the last result for each quarantine run. Run it again just before deleting anything.

**Wait** counts down a waiting time you choose (7, 14 or 30 days; 14 by default). Use your computer normally meanwhile; Put everything back still works.

**Delete** is the only screen that deletes, and only when three conditions hold: the move finished and was not put back, the wait is over, and a SAFE check was made after the wait and within the last 24 hours (**Check the quarantine now** runs one). You also tick a box and confirm. It deletes only the files the moves log lists, each only if its kept copy is still there with the same size; anything else stays in quarantine and is listed in a `deleted_*.csv` log. Empty folders left in the quarantine are removed; anything else in the quarantine folder is left alone.

## Running the tests

```powershell
py -m pip install pytest
py -m pytest
```

## Next steps

1. A Windows installer, so people don't need Python.
2. Try the whole app on a real drive, with a backup first.
