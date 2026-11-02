"""The engine/ scripts keep the old command lines working."""
import os
import subprocess
import sys

import pytest

ENGINE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine")


@pytest.mark.parametrize("script", ["find_dupes", "quarantine_dupes", "compare_backup_sets", "rescue_files"])
def test_help(script):
    r = subprocess.run([sys.executable, os.path.join(ENGINE, script + ".py"), "--help"],
                       capture_output=True, text=True)
    assert r.returncode == 0 and "usage:" in r.stdout


def test_full_run_from_another_folder(tmp_path):
    def run(script, *args):
        return subprocess.run([sys.executable, os.path.join(ENGINE, script + ".py"), *args],
                              capture_output=True, text=True, cwd=tmp_path, check=True).stdout

    run("make_test_data", "data")
    assert "3 duplicate groups, 7 files, 10.21 MB" in run("find_dupes", "data", "--out", "d.csv")
    out = run("quarantine_dupes", "d.csv", "--quarantine", os.path.join("data", "_q"), "--go", "--verify")
    log = out.split("Log: ")[1].splitlines()[0].strip()
    assert "SAFE: every quarantined file" in run("verify_quarantine", log)
    assert "Restored 4 of 4 files." in run("quarantine_dupes", "--undo", log)
