import csv
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dupefinder import testdata  # noqa: E402
from dupefinder.finder import find_duplicates, write_report  # noqa: E402


def write(path, data=b"x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return str(path)


def read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def scan_to_report(roots, out, **kw):
    res = find_duplicates([str(r) for r in roots], log=None, **kw)
    write_report(res.groups, str(out))
    return res


@pytest.fixture
def sample(tmp_path):
    """The make_test_data folder plus its report, with logs going to tmp_path/logs."""
    root = tmp_path / "data"
    testdata.make(str(root))
    report = tmp_path / "report.csv"
    scan_to_report([root], report)
    logs = tmp_path / "logs"
    logs.mkdir()
    return root, report, logs
