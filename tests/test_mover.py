import csv
import os

import pytest

from dupefinder import dryrun, mover, testdata
from dupefinder.finder import find_duplicates
from dupefinder.keepers import Rules, plan
from dupefinder.quarantine import undo
from dupefinder.verify import verify_log


@pytest.fixture
def ready(tmp_path):
    root = tmp_path / "data"
    testdata.make(str(root))
    groups = find_duplicates([str(root)], log=None).groups
    q = {dryrun.volume(str(root)): str(tmp_path / "_q")}
    return root, dryrun.run(plan(groups, Rules()), q), tmp_path


def rows(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def test_moves_exactly_the_dry_run_and_verify_says_safe(ready):
    root, dry, tmp = ready
    res = mover.run(dry, str(tmp / "logs" / "moves.csv"))
    assert (res.moved, res.freed, res.skipped, res.stopped) == (4, testdata.EXPECTED_WASTED, 0, False)
    for m in dry.moving:
        assert not os.path.exists(m.original) and os.path.isfile(m.dest) and os.path.isfile(m.kept)
    v = verify_log(res.log_path)                      # the existing verify tool reads the log
    assert v.safe and v.total == 4


def test_undo_puts_everything_back(ready):
    root, dry, tmp = ready
    before = sorted(str(p) for p in root.rglob("*") if p.is_file())
    res = mover.run(dry, str(tmp / "moves.csv"))
    assert undo(res.log_path, log=lambda s: None) == (4, 4)
    assert sorted(str(p) for p in root.rglob("*") if p.is_file()) == before


def test_changed_since_dry_run_is_not_moved(ready):
    root, dry, tmp = ready
    first = dry.moving[0]
    with open(first.original, "r+b") as f:             # same size, different contents
        f.write(b"\0changed")
    gone = dry.moving[1]
    os.remove(gone.original)
    res = mover.run(dry, str(tmp / "moves.csv"))
    status = {r["original_path"]: r["status"] for r in rows(res.log_path)}
    assert status[first.original] == mover.SKIP_CHANGED and os.path.isfile(first.original)
    assert status[gone.original] == dryrun.SKIP_GONE
    assert res.moved == 2 and res.skipped == 2


def test_without_verify_only_size_is_checked(ready):
    root, dry, tmp = ready
    with open(dry.moving[0].original, "r+b") as f:
        f.write(b"\0changed")
    assert mover.run(dry, str(tmp / "moves.csv"), verify=False).moved == 4


def test_stop_keeps_an_accurate_log(ready):
    root, dry, tmp = ready

    def progress(done, total):
        if done == 2:
            raise mover.Stopped()
    res = mover.run(dry, str(tmp / "moves.csv"), progress=progress)
    assert res.stopped and res.moved == 2
    moved = [r for r in rows(res.log_path) if r["status"] == "moved"]
    assert len(moved) == 2 and all(os.path.isfile(r["quarantine_path"]) for r in moved)


def test_never_overwrites_in_quarantine(ready):
    root, dry, tmp = ready
    m = dry.moving[0]
    os.makedirs(os.path.dirname(m.dest))
    with open(m.dest, "wb") as f:
        f.write(b"older")
    res = mover.run(dry, str(tmp / "moves.csv"))
    assert open(m.dest, "rb").read() == b"older" and os.path.isfile(m.original)
    assert res.moved == 3
