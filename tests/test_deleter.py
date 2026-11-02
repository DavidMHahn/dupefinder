import os
from datetime import datetime, timedelta

import pytest

from dupefinder import deleter, dryrun, mover, testdata
from dupefinder.finder import find_duplicates
from dupefinder.keepers import Rules, plan
from dupefinder.verify import Verdict


@pytest.fixture
def moved(tmp_path):
    root = tmp_path / "data"
    testdata.make(str(root))
    groups = find_duplicates([str(root)], log=None).groups
    q = str(tmp_path / "_q")
    dry = dryrun.run(plan(groups, Rules()), {dryrun.volume(str(root)): q})
    res = mover.run(dry, str(tmp_path / "moves.csv"))
    (tmp_path / "_q" / "not_ours.txt").write_text("someone else's file")
    return root, q, res.log_path, dry, tmp_path


def test_deletes_only_logged_copies_and_prunes_empty_folders(moved):
    root, q, log, dry, tmp = moved
    res = deleter.run(log, [q], str(tmp / "deleted.csv"))
    assert (res.deleted, res.freed, res.kept) == (4, testdata.EXPECTED_WASTED, [])
    assert os.listdir(q) == ["not_ours.txt"]          # unrelated file kept, empty folders gone
    assert all(os.path.isfile(m.kept) for m in dry.moving)


def test_last_copies_are_never_deleted(moved):
    root, q, log, dry, tmp = moved
    os.remove(dry.moving[0].kept)                     # kept copy lost: quarantine holds the last copy
    gone = dry.moving[1]
    os.rename(gone.dest, gone.original)               # put back by hand
    res = deleter.run(log, [q], str(tmp / "deleted.csv"))
    kept = dict((p, s) for s, p in res.kept)
    assert kept[dry.moving[0].dest] == deleter.SKIP_KEPT_MISSING and os.path.isfile(dry.moving[0].dest)
    assert kept[gone.dest] == deleter.SKIP_NOT_THERE
    # the other moving copies share the lost keeper (same group), so only the photo and notes go
    assert res.deleted == sum(1 for m in dry.moving[2:] if m.kept != dry.moving[0].kept)


def test_never_deletes_outside_the_quarantine(moved):
    root, q, log, dry, tmp = moved
    res = deleter.run(log, [str(tmp / "elsewhere")], str(tmp / "deleted.csv"))
    assert res.deleted == 0 and len(res.kept) == 4


def run_info(finished, days=14, **kw):
    r = {"finished": finished, "started": finished, "wait_days": days, "undone": None, "deleted": None}
    r.update(kw)
    return r


def test_checks_gate_deletion():
    now = datetime(2026, 11, 20, 12, 0, 0)
    fmt = "%Y-%m-%d %H:%M:%S"
    moved_at = (now - timedelta(days=15)).strftime(fmt)
    safe_now = ((now - timedelta(hours=1)).strftime(fmt), Verdict(4, 4, []))
    assert all(ok for ok, _ in deleter.checks(run_info(moved_at), safe_now, now))

    early = run_info((now - timedelta(days=3)).strftime(fmt))
    c = deleter.checks(early, safe_now, now)
    assert not c[1][0] and "11 more days" in c[1][1] and not c[2][0]       # check is before the wait ended
    assert not deleter.checks(run_info(moved_at), None, now)[2][0]
    assert not deleter.checks(run_info(moved_at), (safe_now[0], Verdict(3, 4, ["x"])), now)[2][0]
    stale = ((now - timedelta(hours=30)).strftime(fmt), Verdict(4, 4, []))
    long_ago = (now - timedelta(days=20)).strftime(fmt)
    assert "over 24 hours" in deleter.checks(run_info(long_ago), stale, now)[2][1]
    assert not deleter.checks(run_info(moved_at, undone="x"), safe_now, now)[0][0]
    assert not deleter.checks(run_info(moved_at, deleted="x"), safe_now, now)[0][0]
