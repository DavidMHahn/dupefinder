import os

from conftest import read_csv, scan_to_report, write
from dupefinder import backup_sets, rescue
from dupefinder.common import blake2b


def make_sets(tmp_path):
    root = tmp_path / "Backup"
    write(root / "PC_new" / "C" / "Users" / "me" / "Docs" / "cv.docx", b"cv v2")
    write(root / "PC_new" / "C" / "Users" / "me" / "Videos" / "trip.mp4", b"trip")
    write(root / "PC_old" / "C" / "Users" / "me" / "Videos" / "trip.mp4", b"trip")
    write(root / "PC_old" / "C" / "Users" / "me" / "Docs" / "cv.docx", b"cv v1")
    write(root / "PC_old" / "C" / "Users" / "me" / "Videos" / "only_here.mp4", b"unique")
    write(root / "PC_old" / "C" / "Users" / "me" / "Videos" / "only_here_copy.mp4", b"unique")
    report = tmp_path / "backup.csv"
    scan_to_report([root], report)
    return root, report


def test_overview_without_keep(tmp_path):
    root, report = make_sets(tmp_path)
    res = backup_sets.compare(str(root), str(report))
    assert [s.name for s in res.sets] == ["PC_new", "PC_old"]
    assert res.at_risk == []


def test_files_with_no_copy_in_kept_set(tmp_path):
    root, report = make_sets(tmp_path)
    res = backup_sets.compare(str(root), str(report), keep=["PC_new"])
    names = sorted(os.path.basename(p) for _, _, _, p in res.at_risk)
    assert names == ["cv.docx", "only_here.mp4", "only_here_copy.mp4"]
    # the two identical unique videos count once as distinct content
    assert res.distinct_bytes == len(b"cv v1") + len(b"unique")


def test_rescue_moves_and_undoes(tmp_path):
    root, report = make_sets(tmp_path)
    res = backup_sets.compare(str(root), str(report), keep=["PC_new"])
    at_risk = tmp_path / "at_risk.csv"
    backup_sets.write_at_risk(res.at_risk, str(at_risk))
    rows = read_csv(at_risk)
    dest = tmp_path / "Rescued"
    picked = rescue.pick(rows, str(dest), [os.path.join("C", "Users", "me", "Videos")])
    assert len(picked) == 2                       # cv.docx is not under Videos

    dry = rescue.run(picked, go=False, log_dir=str(tmp_path))
    assert dry.moved == 2 and not dest.exists()

    src = root / "PC_old" / "C" / "Users" / "me" / "Videos" / "only_here.mp4"
    digest = blake2b(src)
    done = rescue.run(picked, go=True, log_dir=str(tmp_path))
    assert done.moved == 2 and not src.exists()
    moved_to = dest / "PC_old" / "C" / "Users" / "me" / "Videos" / "only_here.mp4"
    assert blake2b(moved_to) == digest

    assert rescue.undo(done.log_path, log=lambda *a: None) == (2, 2)
    assert blake2b(src) == digest
