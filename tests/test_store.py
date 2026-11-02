import os
import sqlite3

import pytest

from conftest import write
from dupefinder import __version__, finder, testdata
from dupefinder.finder import find_duplicates
from dupefinder.store import Store


@pytest.fixture
def data(tmp_path):
    root = tmp_path / "data"
    testdata.make(str(root))
    return root


def count_reads(monkeypatch):
    calls = []
    real = finder.hash_file

    def counting(path, limit=None):
        calls.append(path)
        return real(path, limit)

    monkeypatch.setattr(finder, "hash_file", counting)
    return calls


def summary(res):
    return [(g.size, g.paths, g.digest) for g in res.groups]


def test_same_result_with_and_without_cache(data, tmp_path):
    plain = find_duplicates([str(data)], log=None)
    with Store(tmp_path / "s.db") as st:
        cached = find_duplicates([str(data)], log=None, store=st)
    assert summary(plain) == summary(cached)


def test_second_scan_reads_nothing(data, tmp_path, monkeypatch):
    db = tmp_path / "s.db"
    with Store(db) as st:
        first = find_duplicates([str(data)], log=None, store=st)
    calls = count_reads(monkeypatch)
    with Store(db) as st:
        second = find_duplicates([str(data)], log=None, store=st)
    assert calls == []
    assert second.cache_hits > 0
    assert summary(first) == summary(second)


def test_changed_file_is_read_again(data, tmp_path, monkeypatch):
    db = tmp_path / "s.db"
    with Store(db) as st:
        find_duplicates([str(data)], log=None, store=st)
    changed = data / "b" / "photo (1).jpg"
    raw = bytearray(changed.read_bytes())
    raw[0] ^= 0xFF                                  # same size, new content
    changed.write_bytes(bytes(raw))
    st_ = os.stat(changed)
    os.utime(changed, ns=(st_.st_atime_ns, st_.st_mtime_ns + 2_000_000_000))
    calls = count_reads(monkeypatch)
    with Store(db) as st:
        res = find_duplicates([str(data)], log=None, store=st)
    assert str(changed) in calls
    assert len(res.groups) == 2                     # the photo pair no longer matches
    assert all(str(changed) not in g.paths for g in res.groups)


def test_interrupted_scan_carries_on(data, tmp_path, monkeypatch):
    """An interruption mid-way keeps the hashes already computed."""
    db = tmp_path / "s.db"
    real = finder.hash_file
    done = []

    class Stopped(Exception):
        """Stands in for Ctrl+C or an unplugged drive."""

    def dies_after_three_full_hashes(path, limit=None):
        if limit is None and len(done) == 3:
            raise Stopped
        digest = real(path, limit)
        if limit is None:
            done.append(path)
        return digest

    monkeypatch.setattr(finder, "hash_file", dies_after_three_full_hashes)
    with pytest.raises(Stopped):
        with Store(db) as st:
            find_duplicates([str(data)], log=None, store=st)

    assert len(done) == 3
    monkeypatch.setattr(finder, "hash_file", real)
    calls = count_reads(monkeypatch)
    with Store(db) as st:
        res = find_duplicates([str(data)], log=None, store=st)
    assert not set(done) & set(calls)               # the 3 finished files were not read again
    assert len(res.groups) == testdata.EXPECTED_GROUPS


def test_saved_scans_reload(data, tmp_path):
    db = tmp_path / "s.db"
    with Store(db) as st:
        res = find_duplicates([str(data)], log=None, store=st)
        scan_id = st.save_scan([str(data)], {"min_size": 1}, res, "2026-11-02 10:00:00")
        scans = st.list_scans()
        assert scans[0]["id"] == scan_id
        assert scans[0]["version"] == __version__
        assert scans[0]["roots"] == [str(data)]
        assert scans[0]["wasted"] == testdata.EXPECTED_WASTED
        assert summary(res) == [(g.size, g.paths, g.digest) for g in st.load_groups(scan_id)]


def test_database_holds_no_file_contents(data, tmp_path):
    db = tmp_path / "s.db"
    with Store(db) as st:
        find_duplicates([str(data)], log=None, store=st)
    con = sqlite3.connect(db)
    cols = [r[1] for r in con.execute("PRAGMA table_info(hashes)")]
    con.close()
    assert cols == ["path", "size", "mtime_ns", "partial", "full"]


def test_cli_db(data, tmp_path, capsys):
    db = tmp_path / "dupefinder.db"
    finder.main([str(data), "--out", str(tmp_path / "a.csv"), "--db", str(db)])
    assert "Saved as scan 1" in capsys.readouterr().out
    finder.main([str(data), "--out", str(tmp_path / "b.csv"), "--db", str(db)])
    out = capsys.readouterr().out
    assert "Saved as scan 2" in out and "hashes reused from the database" in out
    assert (tmp_path / "a.csv").read_bytes() == (tmp_path / "b.csv").read_bytes()


def test_cli_refuses_db_inside_scanned_folder(data, tmp_path):
    with pytest.raises(SystemExit):
        finder.main([str(data), "--out", str(tmp_path / "a.csv"), "--db", str(data / "x.db")])


def test_store_ignores_unknown_columns(tmp_path):
    with Store(tmp_path / "s.db") as st:
        with pytest.raises(AssertionError):
            st.cached(write(tmp_path / "f"), 1, 1, "partial; DROP TABLE hashes")
