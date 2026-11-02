import csv
import os

import pytest

from dupefinder import dryrun, testdata
from dupefinder.dryrun import (
    SKIP_BACKUP, SKIP_DEST, SKIP_GONE, SKIP_IN_Q, SKIP_KEEPER_GONE, SKIP_KEEPER_IN_Q, WOULD_MOVE,
    in_backup_folder, quarantine_path, volume,
)
from dupefinder.finder import find_duplicates
from dupefinder.keepers import Rules, plan
from dupefinder.quarantine import LOG_COLUMNS
from dupefinder.store import Store


@pytest.fixture
def setup(tmp_path):
    root = tmp_path / "data"
    testdata.make(str(root))
    groups = find_duplicates([str(root)], log=None).groups
    q = str(tmp_path / "_q")
    vol = volume(str(root))
    return root, groups, {vol: q}, vol


def snapshot(folder):
    return sorted((p, os.path.getsize(os.path.join(p, f))) for p, _, fs in os.walk(folder) for f in fs)


def test_dry_run_moves_nothing_and_matches_the_plan(setup, tmp_path):
    root, groups, q, vol = setup
    before = snapshot(root)
    dry = dryrun.run(plan(groups, Rules()), q)
    assert snapshot(root) == before and not os.path.exists(q[vol])
    assert len(dry.moving) == 4 and dry.freed == testdata.EXPECTED_WASTED
    for m in dry.moving:
        assert m.dest == quarantine_path(q[vol], vol, m.original)
        assert m.dest.startswith(q[vol] + os.sep) and m.original != m.kept


def test_quarantine_path_keeps_folders():
    vol = os.path.abspath(os.sep)
    assert quarantine_path(os.path.join(vol, "_q"), vol, os.path.join(vol, "Photos", "a.jpg")) == \
        os.path.join(vol, "_q", "Photos", "a.jpg")


def test_changed_and_missing_files_are_skipped(setup):
    root, groups, q, _ = setup
    plans = plan(groups, Rules())
    video = plans[0]
    gone = video.moves[0]
    os.remove(gone)
    with open(plans[1].moves[0], "ab") as f:          # photo copy changed size
        f.write(b"!")
    os.remove(plans[2].keeper)                        # notes: kept copy is gone
    dry = dryrun.run(plans, q)
    status = {m.original: m.status for m in dry.moves}
    assert status[gone] == SKIP_GONE
    assert status[plans[1].moves[0]] == SKIP_GONE
    assert status[plans[2].moves[0]] == SKIP_KEEPER_GONE
    assert dry.reasons()[SKIP_GONE] == 2


def test_backup_folders_are_never_cleaned(tmp_path):
    sep = os.sep
    assert in_backup_folder(f"{sep}J{sep}Toolkit{sep}Backup{sep}PC{sep}a.jpg")
    assert in_backup_folder(f"{sep}D{sep}FileHistory{sep}me{sep}a.jpg")
    assert in_backup_folder(f"{sep}x{sep}Samsung{sep}SmartSwitch{sep}backup{sep}a.jpg")
    assert in_backup_folder(f"{sep}x{sep}WindowsImageBackup{sep}a.vhdx")
    assert not in_backup_folder(f"{sep}J{sep}Backup{sep}a.jpg")
    assert not in_backup_folder(f"{sep}J{sep}Toolkit{sep}a.jpg")

    for d in ("keep", os.path.join("FileHistory", "x")):
        os.makedirs(tmp_path / d)
        (tmp_path / d / "f.bin").write_bytes(b"abc")
    from dupefinder.finder import Group
    groups = [Group(3, [str(tmp_path / "keep" / "f.bin"), str(tmp_path / "FileHistory" / "x" / "f.bin")], "h")]
    dry = dryrun.run(plan(groups, Rules()), {volume(str(tmp_path)): str(tmp_path / "_q")})
    assert [m.status for m in dry.moves] == [SKIP_BACKUP]


def test_quarantine_contents_and_existing_destinations(setup):
    root, groups, q, vol = setup
    plans = plan(groups, Rules())
    dest = quarantine_path(q[vol], vol, plans[0].moves[0])
    os.makedirs(os.path.dirname(dest))
    open(dest, "wb").close()
    assert {m.original: m.status for m in dryrun.run(plans, q).moves}[plans[0].moves[0]] == SKIP_DEST

    # a scan that includes the quarantine folder: its files never move or stay as the only copy
    q2 = {vol: str(root / "c")}
    status = {m.original: m.status for m in dryrun.run(plans, q2).moves}
    assert status[str(root / "c" / "deep" / "video_copy.bin")] == SKIP_IN_Q
    notes = plan(groups, Rules(prefer=[str(root / "c")]))
    assert {m.status for m in dryrun.run(notes, q2).moves if m.group == 3} == {SKIP_KEEPER_IN_Q}


def test_log_is_in_quarantine_tool_format_and_saved(setup, tmp_path):
    root, groups, q, _ = setup
    dry = dryrun.run(plan(groups, Rules()), q)
    out = dryrun.write_log(dry, str(tmp_path / "plan.csv"))
    with open(out, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    assert list(rows[0]) == LOG_COLUMNS and {r["status"] for r in rows} == {WOULD_MOVE}

    with Store(str(tmp_path / "d.db")) as st:
        assert st.latest_dry_run(1) is None
        from dupefinder.finder import ScanResult
        sid = st.save_scan([str(root)], {}, ScanResult(groups=groups), "2026-11-02 12:00:00")
        run_id = st.save_dry_run(sid, dry)
        got_id, _, got = st.latest_dry_run(sid)
        assert got_id == run_id and got.moves == dry.moves and got.quarantines == dry.quarantines


def test_progress_reaches_the_total(setup):
    root, groups, q, _ = setup
    seen = []
    dryrun.run(plan(groups, Rules()), q, progress=lambda d, t: seen.append((d, t)))
    assert seen[-1] == (4, 4)
