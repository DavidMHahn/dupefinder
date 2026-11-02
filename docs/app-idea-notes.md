# Duplicate-cleanup app: notes to pick up from (Nov 2, 2026)

**Goal (Dave):** turn the duplicate-finder toolkit into a user-friendly standalone app, with a good UI/UX, to help other people remove unnecessary duplicate data.

## Where we left off

Nov 2: Dave chose both. The product brief is written: https://claude.ai/artifact/KxF7jRJLySWRBF35YZV4fP (it supersedes the competitor notes below). The repo is waiting for Dave to create an empty private GitHub repository.

### 1. A private GitHub repository (the "what")
- Contents: the six scripts (`find_dupes.py`, `quarantine_dupes.py`, `verify_quarantine.py`, `compare_backup_sets.py`, `rescue_files.py`, `make_test_data.py`), the runbook exported as Markdown, and a few small sample logs with personal paths removed.
- It gives version history and becomes the seed of the app's engine.
- Dave creates the empty repo on GitHub, then Claude attaches it and pushes everything with a README.

### 2. A product brief document (the "why" and "how")
- **The workflow as screens:** scan → review duplicate groups → choose which folder to keep → dry run → quarantine → verify → wait 1–2 weeks → delete. Plus merging drives and mirroring to a backup.
- **Safety rules as features:** read-only scan, dry run by default, same-drive quarantine with undo log, verify before delete, never touching backup-tool folders (Seagate Toolkit, Smart Switch, File History, Windows Backup).
- **Edge cases we hit, as test cases:**
  - Windows junctions (e.g. "My Documents") give access denied. Skip them.
  - OneDrive online-only placeholders would download if read. Exclude them.
  - `--exclude NAME` matched two folders with the same name. Allow excluding by full path.
  - Album art (Folder.jpg, AlbumArt*) is identical across albums but belongs in each folder. Skip it by name.
  - Unicode file names crashed console output when piped. Force UTF-8.
  - Copying a drive root with robocopy makes the destination folder Hidden+System.
  - Robocopy's "g" is GiB, not GB.
  - Windows 7 Backup folders show as 0 bytes and need admin backup mode to read.
  - A verify run after deleting the quarantine shows "quarantined copy missing". That's expected.
  - The keeper choice must ignore copies already in quarantine.
- **Measured performance (USB 3.0 HDDs):** reads at 85–97 MB/s (One Touch) and ~56 MB/s (Canvio). About 22–30 ms per file seek. Drive-to-drive copies ran at ~24 MB/s for mixed files and ~80 MB/s for large videos. Staged hashing (size → first 64 KB → full hash) avoided reading most data: for example, only 90.8 GB of 650.8 GB needed full hashing.
- **Competitor check (to do):** the market is crowded. [AlternativeTo lists dozens of duplicate finders](https://alternativeto.net/software/dupeguru), and [roundups test 15+ free ones](https://softpicker.com/best-free-duplicate-file-finders/). I haven't compared their features yet. **Unverified impression:** most stop at "find and delete". A possible edge is **safety first** (quarantine, verify, undo) plus **backup awareness** (rescuing unique files from old backup sets, merging drives, mirroring to a backup). That should be confirmed with a proper competitor review.

## Next steps when we resume
1. Dave decides: product brief doc first, GitHub repo first, or both.
2. If a repo: Dave creates an empty private repo on GitHub and tells Claude its name.
3. Write the product brief, including a feature-by-feature competitor check.
4. Later: choose the app stack (for example, keep the Python engine with a desktop UI, or rewrite it). Not discussed yet.

## Related files
- Scripts and walkthrough: this folder (`/mnt/project-files/dupe-finder/`)
- Runbook: https://claude.ai/artifact/11yQr7qbbFagNvfDiouuU2
- Drive cleanup status: https://claude.ai/artifact/CyExFE9nbkpYst2PKsZHpF
