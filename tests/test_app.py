"""Tests for the desktop app. They run without a screen (Qt's offscreen mode)."""
import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from dupefinder import testdata  # noqa: E402
from dupefinder.app.scan_screen import ScanScreen  # noqa: E402
from dupefinder.app.window import MainWindow  # noqa: E402
from dupefinder.app.worker import ScanWorker  # noqa: E402
from dupefinder.store import Store  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def data(tmp_path):
    root = tmp_path / "data"
    testdata.make(str(root))
    return root


def wait_for(qapp, condition, seconds=20):
    end = time.monotonic() + seconds
    while not condition():
        if time.monotonic() > end:
            raise AssertionError("timed out")
        qapp.processEvents()
        time.sleep(0.01)


def collect(worker):
    got = {"progress": []}
    worker.progress.connect(lambda *a: got["progress"].append(a))
    worker.finished.connect(lambda res, sid: got.update(result=res, scan_id=sid))
    worker.cancelled.connect(lambda: got.update(cancelled=True))
    worker.failed.connect(lambda msg: got.update(failed=msg))
    return got


def test_window_shows_eight_steps_with_only_scan_enabled(qapp, tmp_path):
    w = MainWindow(db_path=str(tmp_path / "db" / "d.db"))
    assert w.steps.count() == 8
    assert w.enabled_steps() == ["1   Scan"]


def test_worker_finds_known_duplicates_and_saves_scan(qapp, data, tmp_path):
    db = tmp_path / "db" / "d.db"
    worker = ScanWorker([str(data)], db_path=str(db))
    got = collect(worker)
    worker.run()                                    # synchronously, for the test
    res = got["result"]
    assert len(res.groups) == testdata.EXPECTED_GROUPS
    assert res.wasted == testdata.EXPECTED_WASTED
    assert {stage for stage, _, _ in got["progress"]} >= {3, 4}
    with Store(db) as st:
        assert st.list_scans()[0]["id"] == got["scan_id"]


def test_second_scan_reuses_work(qapp, data, tmp_path):
    db = str(tmp_path / "db" / "d.db")
    ScanWorker([str(data)], db_path=db).run()
    worker = ScanWorker([str(data)], db_path=db)
    got = collect(worker)
    worker.run()
    assert got["result"].cache_hits > 0


def test_stop_keeps_work_done(qapp, data, tmp_path):
    db = str(tmp_path / "db" / "d.db")
    worker = ScanWorker([str(data)], db_path=db)
    got = collect(worker)
    worker.progress.connect(lambda stage, d, t: stage == 4 and worker.stop())
    worker.run()
    assert got.get("cancelled") and "result" not in got
    with Store(db) as st:
        assert st.db.execute("SELECT COUNT(*) FROM hashes").fetchone()[0] > 0
        assert st.list_scans() == []                # an unfinished scan is not saved


def test_database_folder_is_never_scanned(qapp, tmp_path):
    db = tmp_path / "db" / "d.db"
    worker = ScanWorker([str(tmp_path)], db_path=str(db))
    assert str(db.parent) in worker.excludes


def test_missing_folder_is_reported(qapp, tmp_path):
    worker = ScanWorker([str(tmp_path / "unplugged")], db_path=str(tmp_path / "db" / "d.db"))
    got = collect(worker)
    worker.run()
    assert got["result"].n_files == 0               # nothing found, no crash


def test_scan_screen_end_to_end(qapp, data, tmp_path):
    screen = ScanScreen(db_path=str(tmp_path / "db" / "d.db"))
    assert not screen.start_button.isEnabled()
    screen.roots.add(str(data))
    assert screen.start_button.isEnabled()
    screen.start_button.click()
    wait_for(qapp, lambda: screen.thread is None)
    assert screen.big["space"].text() == "10.21 MB"
    assert screen.big["groups"].text() == "3"
    assert screen.big["files"].text() == "7"
    assert "Nothing was changed" in screen.detail.text()
    assert screen.start_button.isEnabled()

    out = tmp_path / "report.csv"
    screen.export_csv(str(out))
    assert out.read_text(encoding="utf-8-sig").count("\n") == 1 + testdata.EXPECTED_FILES


def test_adding_the_same_folder_twice(qapp, tmp_path):
    screen = ScanScreen(db_path=str(tmp_path / "d.db"))
    screen.roots.add(str(tmp_path))
    screen.roots.add(str(tmp_path) + os.sep)
    assert screen.roots.folders() == [os.path.normpath(str(tmp_path))]


def test_review_after_scan(qapp, data, tmp_path):
    w = MainWindow(db_path=str(tmp_path / "db" / "d.db"))
    w.scan.roots.add(str(data))
    w.scan.start_button.click()
    wait_for(qapp, lambda: w.scan.thread is None)
    assert w.enabled_steps() == ["1   Scan", "2   Review groups"]
    assert w.scan.next_button.isEnabled()
    w.scan.next_button.click()
    assert w.pages.currentWidget() is w.review

    r = w.review
    assert r.summary.text().startswith("10.21 MB could be freed: 3 groups, 7 files")
    assert r.table.rowCount() == len(r.sets) >= 1
    # biggest saving first, and the first row is selected with its files listed
    first = r.selected_set()
    assert first.wasted == max(fs.wasted for fs in r.sets)
    assert r.tree.topLevelItemCount() == len(first.groups)
    child = r.tree.topLevelItem(0).child(0)
    assert os.path.isfile(child.data(0, 0x0100))                  # Qt.UserRole holds the path


def test_review_filter(qapp, data, tmp_path):
    db = str(tmp_path / "db" / "d.db")
    ScanWorker([str(data)], db_path=db).run()
    w = MainWindow(db_path=db)
    assert "2   Review groups" in w.enabled_steps()                # a saved scan exists
    r = w.review
    r.filter.setText("notes")
    assert r.table.rowCount() == 1
    assert "notes" in r.tree.topLevelItem(0).child(0).text(0)
    r.filter.setText("no such thing")
    assert r.table.rowCount() == 0 and r.detail_title.text() == "Nothing matches the filter"


def test_review_picks_earlier_scan(qapp, data, tmp_path):
    db = str(tmp_path / "db" / "d.db")
    ScanWorker([str(data)], db_path=db).run()
    ScanWorker([str(data / "a")], db_path=db).run()              # second scan: no duplicates
    w = MainWindow(db_path=db)
    r = w.review
    assert r.scans.count() == 2
    assert r.summary.text() == "No duplicates in this scan."      # newest first
    r.scans.setCurrentIndex(1)
    assert r.summary.text().startswith("10.21 MB")
