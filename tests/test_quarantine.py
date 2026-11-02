import os

from conftest import read_csv, scan_to_report, write
from dupefinder import quarantine, testdata
from dupefinder.common import blake2b
from dupefinder.verify import verify_log


def files_under(root):
    return sorted(os.path.relpath(os.path.join(d, f), root)
                  for d, _, fs in os.walk(root) for f in fs)


def test_dry_run_changes_nothing(sample):
    root, report, logs = sample
    before = files_under(root)
    out = quarantine.run(str(report), str(root / "_q"), log_dir=str(logs))
    assert files_under(root) == before
    assert not (root / "_q").exists()
    assert out.moved == testdata.EXPECTED_FILES - testdata.EXPECTED_GROUPS
    assert out.freed == testdata.EXPECTED_WASTED
    assert os.path.basename(out.log_path).startswith("dryrun_")
    assert {r["status"] for r in read_csv(out.log_path)} == {"would move"}


def test_go_moves_extras_and_keeps_one_of_each(sample):
    root, report, logs = sample
    q = root / "_q"
    out = quarantine.run(str(report), str(q), go=True, verify=True, log_dir=str(logs))
    assert out.moved == 4
    rows = read_csv(out.log_path)
    for r in rows:
        assert r["status"] == "moved"
        assert os.path.isfile(r["kept_path"])
        assert not os.path.exists(r["original_path"])
        assert os.path.isfile(r["quarantine_path"])
        assert r["quarantine_path"].startswith(str(q))
    # default rule keeps the shortest path
    kept = {os.path.relpath(r["kept_path"], root) for r in rows}
    assert os.path.join("a", "video_copy.bin") in kept


def test_undo_restores_everything(sample):
    root, report, logs = sample
    before = {p: blake2b(os.path.join(root, p)) for p in files_under(root)}
    out = quarantine.run(str(report), str(root / "_q"), go=True, log_dir=str(logs))
    restored, total = quarantine.undo(out.log_path, log=lambda *a: None)
    assert (restored, total) == (4, 4)
    after = {p: blake2b(os.path.join(root, p)) for p in files_under(root)}
    assert after == before


def test_only_under_keeps_the_copy_outside(tmp_path):
    keep = write(tmp_path / "Archive" / "deep" / "er" / "v.mp4", b"video")
    extra = write(tmp_path / "PhoneDump" / "v.mp4", b"video")
    report = tmp_path / "r.csv"
    scan_to_report([tmp_path], report)
    out = quarantine.run(str(report), str(tmp_path / "_q"), go=True,
                         only_under=[str(tmp_path / "PhoneDump")], log_dir=str(tmp_path))
    assert out.moved == 1
    assert os.path.isfile(keep) and not os.path.exists(extra)


def test_only_under_never_moves_copies_outside(tmp_path):
    a = write(tmp_path / "A" / "x.bin", b"dup")
    b = write(tmp_path / "B" / "x.bin", b"dup")
    write(tmp_path / "Dump" / "x.bin", b"dup")
    report = tmp_path / "r.csv"
    scan_to_report([tmp_path], report)
    quarantine.run(str(report), str(tmp_path / "_q"), go=True,
                   only_under=[str(tmp_path / "Dump")], log_dir=str(tmp_path))
    assert os.path.isfile(a) and os.path.isfile(b)


def test_prefer(tmp_path):
    write(tmp_path / "a" / "x.bin", b"dup")
    b = write(tmp_path / "Best" / "deeper" / "x.bin", b"dup")
    report = tmp_path / "r.csv"
    scan_to_report([tmp_path], report)
    quarantine.run(str(report), str(tmp_path / "_q"), go=True,
                   prefer=str(tmp_path / "Best"), log_dir=str(tmp_path))
    assert os.path.isfile(b)


def test_skip_name_leaves_album_art(tmp_path):
    """Edge case 4: identical Folder.jpg and desktop.ini belong in every album folder."""
    for album in ("Album1", "Album2"):
        write(tmp_path / "Music" / album / "Folder.jpg", b"same cover")
        write(tmp_path / "Music" / album / "AlbumArtSmall.jpg", b"same small")
        write(tmp_path / "Music" / album / "desktop.ini", b"[ini]")
    write(tmp_path / "Music" / "Album1" / "song.mp3", b"song")
    song2 = write(tmp_path / "Music" / "Album2" / "song.mp3", b"song")
    report = tmp_path / "r.csv"
    scan_to_report([tmp_path], report)
    out = quarantine.run(str(report), str(tmp_path / "_q"), go=True, log_dir=str(tmp_path),
                         skip_names=["folder.JPG", "AlbumArt*", "desktop.ini"])
    assert out.moved == 1
    assert not os.path.exists(song2)
    for album in ("Album1", "Album2"):
        for name in ("Folder.jpg", "AlbumArtSmall.jpg", "desktop.ini"):
            assert (tmp_path / "Music" / album / name).is_file()


def test_copy_in_quarantine_is_never_the_keeper(tmp_path):
    """Edge case 10: a scan that included the quarantine must not keep the quarantined copy."""
    q = tmp_path / "_q"
    write(q / "old" / "x.bin", b"dup")
    a = write(tmp_path / "data" / "x.bin", b"dup")
    report = tmp_path / "r.csv"
    scan_to_report([tmp_path], report)
    out = quarantine.run(str(report), str(q), go=True, log_dir=str(tmp_path))
    assert out.moved == 0          # only one copy left outside the quarantine
    assert os.path.isfile(a)


def test_verify_skips_files_changed_since_the_scan(sample):
    root, report, logs = sample
    changed = root / "b" / "photo (1).jpg"
    data = bytearray(changed.read_bytes())
    data[0] ^= 0xFF                 # same size, different content
    changed.write_bytes(bytes(data))
    out = quarantine.run(str(report), str(root / "_q"), go=True, verify=True, log_dir=str(logs))
    assert changed.is_file()
    statuses = [r["status"] for r in read_csv(out.log_path)]
    assert "skipped: contents changed since report" in statuses
    assert out.moved == 3


def test_group_with_one_copy_left_is_skipped(sample):
    root, report, logs = sample
    os.remove(root / "c" / "notes_backup.txt")
    out = quarantine.run(str(report), str(root / "_q"), go=True, log_dir=str(logs))
    assert (root / "a" / "notes.txt").is_file()
    assert "skipped: fewer than 2 copies still present" in [r["status"] for r in read_csv(out.log_path)]


def test_existing_file_in_quarantine_is_not_overwritten(sample):
    root, report, logs = sample
    q = root / "_q"
    blocker = write(quarantine.quarantine_path(str(q), str(root / "b" / "photo (1).jpg")), b"other")
    out = quarantine.run(str(report), str(q), go=True, log_dir=str(logs))
    assert open(blocker, "rb").read() == b"other"
    assert (root / "b" / "photo (1).jpg").is_file()
    assert out.moved == 3


def test_quarantine_path_keeps_structure():
    q = os.path.abspath(os.path.join("Q", "_dupes"))
    p = os.path.abspath(os.path.join("Photos", "2020", "a.jpg"))
    dest = quarantine.quarantine_path(q, p)
    assert dest.startswith(q)
    assert dest.endswith(os.path.join("Photos", "2020", "a.jpg"))


def test_moved_batch_verifies_safe(sample):
    root, report, logs = sample
    out = quarantine.run(str(report), str(root / "_q"), go=True, log_dir=str(logs))
    v = verify_log(out.log_path)
    assert v.safe and v.ok == 4
