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
