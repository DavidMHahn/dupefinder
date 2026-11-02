"""READ-ONLY check to run BEFORE you delete a quarantine folder.

For every file a moves log says was quarantined, it confirms:
  1. the kept copy still exists at kept_path
  2. the quarantined copy still exists at quarantine_path
  3. both have the same size and the same BLAKE2b hash
  4. nothing was put back at original_path since (if it was, it is reported)

Only when every row passes is it safe to delete the quarantine folder.

  py verify_quarantine.py C:\\dupefinder\\moves_20261030_175000.csv
"""

import csv
import os
import sys
from dataclasses import dataclass, field

from .common import blake2b, utf8_stdout


@dataclass
class Verdict:
    ok: int = 0
    total: int = 0
    problems: list = field(default_factory=list)

    @property
    def safe(self):
        return self.ok == self.total

    def summary(self):
        """{problem kind: count}, e.g. {'KEPT COPY MISSING': 2}."""
        kinds = {}
        for p in self.problems:
            k = p.split(":", 1)[0]
            kinds[k] = kinds.get(k, 0) + 1
        return kinds


def verify_log(log_path):
    """Check every 'moved' row of a moves log and return a Verdict."""
    with open(log_path, newline="", encoding="utf-8-sig") as f:
        rows = [r for r in csv.DictReader(f) if r["status"] == "moved"]

    v = Verdict(total=len(rows))
    for r in rows:
        kept, quar, orig = r["kept_path"], r["quarantine_path"], r["original_path"]
        if not os.path.isfile(kept):
            v.problems.append(f"KEPT COPY MISSING: {kept}  (do not delete {quar})")
        elif not os.path.isfile(quar):
            if os.path.isfile(orig):
                v.problems.append(f"already restored to original place: {orig}")
            else:
                v.problems.append(f"quarantined copy missing: {quar}")
        elif os.path.getsize(kept) != os.path.getsize(quar) or blake2b(kept) != blake2b(quar):
            v.problems.append(f"KEPT COPY CHANGED, no longer identical: {kept}  (do not delete {quar})")
        else:
            v.ok += 1
    return v


def main(argv=None):
    utf8_stdout()
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        sys.exit("usage: py verify_quarantine.py <moves_log.csv>")
    v = verify_log(argv[0])

    for p in v.problems:
        print("  " + p)
    kinds = v.summary()
    if kinds:
        print("Problem summary:")
        for k, n in sorted(kinds.items()):
            print(f"  {n:,}  {k}")
    print(f"{v.ok:,} of {v.total:,} quarantined files verified: kept copy present and identical.")
    if v.safe:
        print("SAFE: every quarantined file has an identical kept copy.")
    else:
        print("NOT SAFE to delete the whole quarantine folder. Review the lines above first.")
        sys.exit(1)
    return v


if __name__ == "__main__":
    main()
