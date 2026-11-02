import os
import sys

import pytest

from conftest import read_csv, scan_to_report, write
from dupefinder import finder, testdata
from dupefinder.finder import find_duplicates


def test_known_duplicates(tmp_path):
    root = tmp_path / "data"
    testdata.make(str(root))
    res = find_duplicates([str(root)], log=None)
    assert len(res.groups) == testdata.EXPECTED_GROUPS
    assert res.dup_files == testdata.EXPECTED_FILES
    assert res.wasted == testdata.EXPECTED_WASTED
    names = {os.path.basename(p) for g in res.groups for p in g.paths}
    # same size but different start, same first 64 KB but different end, and empty files
    assert not names & {"same_size_1.bin", "same_head_1.bin", "empty.txt"}
    # largest waste first
    assert res.groups[0].size == 5_000_000


def test_full_hash_only_where_needed(tmp_path):
    """Stage 4 reads in full only files whose size and first 64 KB both match."""
    root = tmp_path / "data"
    testdata.make(str(root))
    res = find_duplicates([str(root)], log=None)
    # 3 x 5 MB + 2 x 200 KB + 2 same-head files of 565,536 bytes; the 10 KB pair is done in stage 3
    assert res.full_hash_bytes == 3 * 5_000_000 + 2 * 200_000 + 2 * (64 * 1024 + 500_000)


def test_scan_only_reads_no_contents(tmp_path, monkeypatch):
    root = tmp_path / "data"
    testdata.make(str(root))
    monkeypatch.setattr(finder, "hash_file", lambda *a, **k: pytest.fail("hashed a file"))
    res = find_duplicates([str(root)], scan_only=True, log=None)
    assert res.groups == []
    assert res.candidate_files > 0


def test_report_columns_and_round_trip(sample):
    root, report, logs = sample
    rows = read_csv(report)
    assert list(rows[0]) == finder.REPORT_COLUMNS
    assert len(rows) == testdata.EXPECTED_FILES


def test_two_roots_are_compared(tmp_path):
    a = write(tmp_path / "K" / "photo.jpg", b"same")
    b = write(tmp_path / "L" / "copy.jpg", b"same")
    res = find_duplicates([str(tmp_path / "K"), str(tmp_path / "L")], log=None)
    assert [sorted(g.paths) for g in res.groups] == [sorted([a, b])]


def test_min_size(tmp_path):
    write(tmp_path / "a" / "x", b"12")
    write(tmp_path / "b" / "x", b"12")
    assert len(find_duplicates([str(tmp_path)], min_size=3, log=None).groups) == 0
    assert len(find_duplicates([str(tmp_path)], min_size=2, log=None).groups) == 1


def test_exclude_by_name_skips_every_folder_with_that_name(tmp_path):
    """Edge case 3: a name matched two folders, which silently dropped 99.8 GB."""
    write(tmp_path / "Old" / "a.bin", b"dup")
    write(tmp_path / "History" / "Old" / "b.bin", b"dup")
    write(tmp_path / "keep" / "c.bin", b"dup")
    res = find_duplicates([str(tmp_path)], exclude=["Old"], log=None)
    assert res.n_files == 1


def test_exclude_by_full_path_skips_only_that_folder(tmp_path):
    write(tmp_path / "Old" / "a.bin", b"dup")
    b = write(tmp_path / "History" / "Old" / "b.bin", b"dup")
    c = write(tmp_path / "keep" / "c.bin", b"dup")
    res = find_duplicates([str(tmp_path)], exclude=[str(tmp_path / "Old")], log=None)
    assert [g.paths for g in res.groups] == [sorted([b, c])]


def test_windows_system_folders_skipped(tmp_path):
    write(tmp_path / "$RECYCLE.BIN" / "a.bin", b"dup")
    write(tmp_path / "System Volume Information" / "b.bin", b"dup")
    write(tmp_path / "c.bin", b"dup")
    assert find_duplicates([str(tmp_path)], log=None).n_files == 1


def test_links_are_not_followed(tmp_path):
    """Edge case 1: junctions such as "My Documents" must be skipped, not followed."""
    real = tmp_path / "real"
    write(real / "a.bin", b"dup")
    write(real / "b.bin", b"dup")
    try:
        os.symlink(real, tmp_path / "link", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("creating symbolic links needs extra rights here")
    res = find_duplicates([str(tmp_path)], log=None)
    assert res.n_files == 2
    assert all(str(tmp_path / "link") not in p for g in res.groups for p in g.paths)


def test_unreadable_folder_does_not_stop_the_scan(tmp_path, monkeypatch):
    write(tmp_path / "ok" / "a.bin", b"dup")
    write(tmp_path / "ok" / "b.bin", b"dup")
    real_scandir = os.scandir

    def scandir(path):
        if str(path).endswith("ok"):
            raise PermissionError("access denied")
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", scandir)
    res = find_duplicates([str(tmp_path)], log=None)
    assert res.n_files == 0       # skipped with a message, no crash


def test_unicode_names(tmp_path, capsys):
    """Edge case 5: names in any language must scan, report and print."""
    a = write(tmp_path / "data" / "café ☕.jpg", b"dup")
    b = write(tmp_path / "data" / "日本語" / "写真.jpg", b"dup")
    report = tmp_path / "r.csv"
    scan_to_report([tmp_path / "data"], report)
    assert {r["path"] for r in read_csv(report)} == {a, b}


def test_report_inside_scanned_folder_refused(tmp_path):
    write(tmp_path / "a.bin")
    with pytest.raises(SystemExit):
        finder.main([str(tmp_path), "--out", str(tmp_path / "dupes.csv")])


def test_cli_end_to_end(tmp_path, capsys):
    root = tmp_path / "data"
    testdata.make(str(root))
    out = tmp_path / "dupes.csv"
    finder.main([str(root), "--out", str(out)])
    text = capsys.readouterr().out
    assert "Stage 5: 3 duplicate groups, 7 files, 10.21 MB could be freed" in text
