# dupefinder

Finds duplicate files on a drive, guides you through the detection, analysis, quarantine, and deletion of duplicate files.

This repository holds the command-line toolkit that cleaned up about 563 GB of duplicates across three Windows drives (Oct 30 to Nov 1, 2026), and is the starting point for a user-friendly desktop app.

## The rule

Nothing is deleted until a verified quarantine has waited. Scanning is read-only, moves are dry runs by default, every move is logged and can be undone, and a verify step must say SAFE before you delete a quarantine folder by hand.

## What's here

| Path | What it is |
|---|---|
| `engine/find_dupes.py` | Read-only scan of one or more folders or drives: size, then first 64 KB, then full BLAKE2b hash. Writes a CSV report. |
| `engine/quarantine_dupes.py` | Moves extra copies to a quarantine folder on the same drive. Dry run by default; `--go` to move, `--verify` to re-hash first, `--undo LOG` to restore. Keeper rules: `--only-under`, `--prefer`, `--skip-name`. |
| `engine/verify_quarantine.py` | Read-only check of a moves log: SAFE or NOT SAFE, with a problem summary. |
| `engine/compare_backup_sets.py` | Read-only: lists files in an old backup set that have no identical copy in the sets you keep. |
| `engine/rescue_files.py` | Moves those at-risk files out of the old set before it is deleted (dry run, `--go`, `--undo`). |
| `engine/make_test_data.py` | Builds a throwaway folder with known duplicates (3 groups, 7 files, 10.21 MB) for rehearsals and tests. |
| `docs/runbook.md` | Step-by-step runbook with every command, gotchas, and the scripts as they were used. |
| `docs/walkthrough.md` | First-time walkthrough on test data. |
| `docs/app-idea-notes.md` | Notes for the standalone app. The full product brief is a separate document. |

## Quick start (Windows, Python 3.9+)

```powershell
py engine\make_test_data.py C:\dupetest
py engine\find_dupes.py C:\dupetest --out C:\dupefinder\test.csv
py engine\quarantine_dupes.py C:\dupefinder\test.csv              # dry run, changes nothing
py engine\quarantine_dupes.py C:\dupefinder\test.csv --go --verify
py engine\verify_quarantine.py <moves log printed above>
```

Never run the tools inside live backup folders (Seagate Toolkit, Samsung Smart Switch, File History, Windows Backup).

## Next steps

1. Turn the scripts into one Python package with automated tests built from the edge cases in the product brief.
2. Store scan results in SQLite (hash cache, resumable scans).
3. Build the desktop UI (planned: PySide6, Windows first).
