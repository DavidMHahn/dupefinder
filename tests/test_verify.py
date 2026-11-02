import os
import shutil

import pytest

from dupefinder import quarantine, verify


@pytest.fixture
def moved(sample):
    root, report, logs = sample
    out = quarantine.run(str(report), str(root / "_q"), go=True, log_dir=str(logs))
    return root, out.log_path


def test_safe(moved):
    root, log = moved
    v = verify.verify_log(log)
    assert v.safe and v.problems == []


def test_kept_copy_missing_is_not_safe(moved):
    root, log = moved
    os.remove(root / "a" / "photo.jpg")
    v = verify.verify_log(log)
    assert not v.safe
    assert v.summary() == {"KEPT COPY MISSING": 1}


def test_kept_copy_changed_is_not_safe(moved):
    root, log = moved
    with open(root / "a" / "notes.txt", "r+b") as f:
        f.write(b"edited")
    v = verify.verify_log(log)
    assert v.summary() == {"KEPT COPY CHANGED, no longer identical": 1}


def test_after_undo(moved):
    root, log = moved
    quarantine.undo(log, log=lambda *a: None)
    assert verify.verify_log(log).summary() == {"already restored to original place": 4}


def test_after_quarantine_deleted(moved):
    """Edge case 9: once the quarantine is deleted every row reports the quarantined
    copy missing. That is expected; only KEPT COPY lines would matter."""
    root, log = moved
    shutil.rmtree(root / "_q")
    v = verify.verify_log(log)
    assert v.summary() == {"quarantined copy missing": 4}
    assert not any(p.startswith("KEPT COPY") for p in v.problems)


def test_cli_exit_codes(moved, capsys):
    root, log = moved
    verify.main([log])
    assert "SAFE: every quarantined file" in capsys.readouterr().out
    os.remove(root / "a" / "photo.jpg")
    with pytest.raises(SystemExit) as e:
        verify.main([log])
    assert e.value.code == 1
    assert "NOT SAFE" in capsys.readouterr().out


def test_progress_and_unreadable_files(tmp_path, monkeypatch):
    import csv as _csv
    log = tmp_path / "moves.csv"
    kept, quar = tmp_path / "k.bin", tmp_path / "q.bin"
    kept.write_bytes(b"same")
    quar.write_bytes(b"same")
    with open(log, "w", newline="", encoding="utf-8-sig") as f:
        w = _csv.writer(f)
        w.writerow(quarantine.LOG_COLUMNS)
        w.writerow([1, "moved", str(kept), str(tmp_path / "orig.bin"), str(quar), 4])
    seen = []
    assert verify.verify_log(str(log), lambda d, t: seen.append((d, t))).safe
    assert seen == [(0, 1), (1, 1)]

    def unreadable(path):
        raise PermissionError(13, "Permission denied", path)
    monkeypatch.setattr(verify, "blake2b", unreadable)
    v = verify.verify_log(str(log))
    assert not v.safe and v.problems[0].startswith("COULD NOT READ")
