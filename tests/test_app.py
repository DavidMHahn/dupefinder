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
    assert w.enabled_steps() == ["1   Scan", "2   Review groups", "3   Choose keepers", "4   Dry run", "5   Quarantine", "6   Verify", "7   Wait", "8   Delete"]
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


def test_no_keepers_step_for_a_scan_without_duplicates(qapp, data, tmp_path):
    db = str(tmp_path / "db" / "d.db")
    ScanWorker([str(data / "a")], db_path=db).run()
    w = MainWindow(db_path=db)
    assert w.enabled_steps() == ["1   Scan", "2   Review groups"]
    assert not w.review.next_button.isEnabled()


def keepers_window(data, tmp_path):
    db = str(tmp_path / "db" / "d.db")
    ScanWorker([str(data)], db_path=db).run()
    w = MainWindow(db_path=db)
    w.go(2)
    w.review.next_button.click()
    assert w.pages.currentWidget() is w.keepers
    return w, db


def test_keepers_default_rules(qapp, data, tmp_path):
    w, _ = keepers_window(data, tmp_path)
    k = w.keepers
    assert k.summary.text().startswith("4 extra copies would move to quarantine, freeing 10.21 MB. "
                                       "One copy stays in each of 3 groups.")
    assert k.tree.topLevelItemCount() == 3
    video = k.tree.topLevelItem(0)                      # biggest first
    decisions = {video.child(i).text(0): video.child(i).text(1) for i in range(video.childCount())}
    assert decisions[str(data / "a" / "video_copy.bin")] == "Keep"
    assert decisions[str(data / "c" / "deep" / "video_copy.bin")] == "Move to quarantine"
    assert k.next_button.isEnabled()


def test_keepers_pick_by_hand_is_saved(qapp, data, tmp_path):
    w, db = keepers_window(data, tmp_path)
    k = w.keepers
    video = k.tree.topLevelItem(0)
    deep = next(video.child(i) for i in range(video.childCount()) if "deep" in video.child(i).text(0))
    k.tree.setCurrentItem(deep)
    assert k.keep_button.isEnabled()
    k.keep_button.click()
    assert "1 picked by hand" in k.summary.text()
    assert k.plans[0].keeper == str(data / "c" / "deep" / "video_copy.bin")
    assert k.reset_button.isEnabled()                   # selection survives the refresh

    again = MainWindow(db_path=db)                      # come back later: the pick is remembered
    again.go(3)
    assert again.keepers.plans[0].keeper == str(data / "c" / "deep" / "video_copy.bin")
    again.keepers.tree.setCurrentItem(again.keepers.tree.topLevelItem(0))
    again.keepers.reset_button.click()
    assert again.keepers.plans[0].keeper == str(data / "a" / "video_copy.bin")


def test_keepers_rules_change_the_plan(qapp, data, tmp_path):
    w, db = keepers_window(data, tmp_path)
    k = w.keepers
    k.prefer.add(str(data / "b"))
    assert k.plans[0].keeper == str(data / "b" / "video_copy.bin")
    k.only_from.add(str(data / "c"))
    t = [gp for gp in k.plans if gp.moves]
    assert all(m.startswith(str(data / "c")) for gp in t for m in gp.moves)
    assert "stay because of a folder or name rule" in k.summary.text()
    k.skip.setText("*.txt")
    k.skip.editingFinished.emit()
    assert all(not m.endswith(".txt") for gp in k.plans for m in gp.moves)
    with Store(db) as st:
        rules, _ = st.load_choices(k.scan_id)
    assert rules["prefer"] == [str(data / "b")] and rules["skip_names"] == ["*.txt"]


def test_keepers_filter(qapp, data, tmp_path):
    w, _ = keepers_window(data, tmp_path)
    k = w.keepers
    k.filter.setText("photo")
    assert k.tree.topLevelItemCount() == 1 and k.shown_note.text() == "1 group matches"


def dryrun_window(data, tmp_path):
    w, db = keepers_window(data, tmp_path)
    w.keepers.next_button.click()
    assert w.pages.currentWidget() is w.dryrun
    d = w.dryrun
    vol = next(iter(d.quarantines))
    assert d.set_quarantine(vol, str(tmp_path / "_q"))
    return w, d, db


def test_dry_run_screen(qapp, data, tmp_path):
    w, d, db = dryrun_window(data, tmp_path)
    assert d.qtable.rowCount() == 1 and d.qtable.item(0, 2).text() == "4"
    assert d.summary.text() == ""
    d.run_button.click()
    wait_for(qapp, lambda: d.thread is None)
    assert d.summary.text() == "4 copies would move to quarantine, freeing 10.21 MB."
    assert d.proxy.rowCount() == 4
    assert all(os.path.exists(p) for p in (data / "b" / "video_copy.bin", data / "c" / "deep" / "video_copy.bin"))
    assert not (tmp_path / "_q").exists()                 # nothing moved
    out = d.export_csv(str(tmp_path / "plan.csv"))
    assert open(out, encoding="utf-8-sig").read().count("would move") == 4
    assert d.next_button.isEnabled()

    # come back later: the saved dry run is shown, until a keeper choice changes
    again = MainWindow(db_path=db)
    again.go(4)
    assert again.dryrun.summary.text().startswith("4 copies would move")
    assert again.dryrun.quarantines[next(iter(again.dryrun.quarantines))] == str(tmp_path / "_q")
    with Store(db) as st:
        st.db.execute("UPDATE dry_runs SET created = '2000-01-01 00:00:00'")
        st.save_choices(again.review.scan_id, {"keep": "alpha"}, {})
    again.go(3)
    again.go(4)
    assert again.dryrun.summary.text() == "" and "run the dry run" in again.dryrun.stage.text()


def test_dry_run_filter_and_skips(qapp, data, tmp_path):
    w, d, _ = dryrun_window(data, tmp_path)
    os.remove(data / "c" / "notes_backup.txt")
    d.run_button.click()
    wait_for(qapp, lambda: d.thread is None)
    assert "3 copies would move" in d.summary.text() and "1 skipped" in d.summary.text()
    assert "file no longer there" in d.reasons.text()
    d.show_combo.setCurrentIndex(2)
    assert d.proxy.rowCount() == 1
    d.show_combo.setCurrentIndex(1)
    d.filter.setText("photo")
    assert d.proxy.rowCount() == 1


def test_quarantine_must_be_on_the_same_drive(qapp, data, tmp_path):
    w, d, _ = dryrun_window(data, tmp_path)
    assert not d.set_quarantine("Z:" + os.sep, str(tmp_path / "_q2"))


def quarantine_window(qapp, data, tmp_path):
    w, d, db = dryrun_window(data, tmp_path)
    d.run_button.click()
    wait_for(qapp, lambda: d.thread is None)
    d.next_button.click()
    q = w.quarantine
    assert w.pages.currentWidget() is q
    q.confirm = lambda title, text: True
    q.errors = []
    q.error = lambda title, text: q.errors.append(text)
    return w, q, db


def files(root):
    return sorted(str(p) for p in root.rglob("*") if p.is_file())


def test_quarantine_moves_and_puts_back(qapp, data, tmp_path):
    w, q, db = quarantine_window(qapp, data, tmp_path)
    before = files(data)
    assert q.ready.text().startswith("Ready to move 4 copies to quarantine, freeing 10.21 MB")
    assert q.start_button.text() == "Move 4 copies to quarantine"
    q.start_button.click()
    wait_for(qapp, lambda: q.thread is None)
    assert q.result_title.text() == "Moved 4 copies to quarantine, freeing 10.21 MB"
    assert q.stage.text() == "Done. Nothing was deleted."
    assert len(files(data)) == len(before) - 4 and len(files(tmp_path / "_q")) == 4
    assert not q.start_button.isEnabled() and "has been carried out" in q.ready.text()
    log = q.last_run["log_path"]
    assert os.path.dirname(os.path.dirname(log)) == os.path.dirname(db)       # <db folder>/logs

    again = MainWindow(db_path=db)                    # come back later: undo still available
    again.go(5)
    a = again.quarantine
    a.confirm = lambda title, text: True
    assert a.undo_button.isEnabled()
    a.undo_button.click()
    wait_for(qapp, lambda: a.thread is None)
    assert files(data) == before and files(tmp_path / "_q") == []
    assert a.result_title.text() == "Everything was put back"
    assert a.start_button.isEnabled()                 # the same dry run can be carried out again


def test_quarantine_needs_a_current_dry_run(qapp, data, tmp_path):
    db = str(tmp_path / "db" / "d.db")
    ScanWorker([str(data)], db_path=db).run()
    w = MainWindow(db_path=db)
    w.go(5)
    assert "Run the dry run first" in w.quarantine.ready.text()
    assert not w.quarantine.start_button.isEnabled()


def test_quarantine_cancelled_confirmation_moves_nothing(qapp, data, tmp_path):
    w, q, _ = quarantine_window(qapp, data, tmp_path)
    before = files(data)
    q.confirm = lambda title, text: False
    q.start_button.click()
    assert q.thread is None and files(data) == before


def verify_window(qapp, data, tmp_path):
    w, q, db = quarantine_window(qapp, data, tmp_path)
    q.start_button.click()
    wait_for(qapp, lambda: q.thread is None)
    assert q.next_button.isEnabled()
    q.next_button.click()
    assert w.pages.currentWidget() is w.verify
    return w, w.verify, db


def test_verify_safe_then_not_safe(qapp, data, tmp_path):
    w, v, db = verify_window(qapp, data, tmp_path)
    assert v.picker.count() == 1 and v.stage.text() == "Not checked yet."
    v.check_button.click()
    wait_for(qapp, lambda: v.thread is None)
    assert v.verdict_label.text() == "SAFE" and v.verdict.total == 4
    assert not v.problems.isVisible()

    kept = w.quarantine.dry.moving[0].kept
    with open(kept, "r+b") as f:                      # a kept copy changes after quarantine
        f.write(b"\0changed")
    v.check_button.click()
    wait_for(qapp, lambda: v.thread is None)
    assert v.verdict_label.text() == "NOT SAFE to delete"
    assert "kept copy changed" in v.detail.text() and v.problems.count() >= 1

    again = MainWindow(db_path=db)                    # the last result is remembered
    again.go(6)
    assert again.verify.verdict_label.text() == "NOT SAFE to delete"


def test_verify_lists_nothing_after_undo(qapp, data, tmp_path):
    w, v, db = verify_window(qapp, data, tmp_path)
    q = w.quarantine
    q.undo_button.click()
    wait_for(qapp, lambda: q.thread is None)
    w.go(5)
    w.go(6)
    assert v.picker.count() == 0 and not v.check_button.isEnabled()
    assert "Nothing is in quarantine" in v.stage.text()


def test_wait_and_delete(qapp, data, tmp_path):
    from datetime import datetime, timedelta
    w, v, db = verify_window(qapp, data, tmp_path)
    v.check_button.click()
    wait_for(qapp, lambda: v.thread is None)
    assert v.next_button.isEnabled()                  # SAFE
    v.next_button.click()
    wt = w.wait
    assert w.pages.currentWidget() is wt
    assert wt.status.text() == "14 days to go" and not wt.next_button.isEnabled()
    wt.days.setCurrentIndex(0)                        # 7 days, saved
    assert wt.status.text() == "7 days to go"
    later = datetime.now() + timedelta(days=8)
    wt.now = lambda: later
    wt.load(wt.scan_id)
    assert wt.status.text() == "The wait is over" and wt.next_button.isEnabled()

    wt.next_button.click()
    d = w.delete
    assert w.pages.currentWidget() is d
    d.now = lambda: later
    d.load(d.scan_id)
    # the SAFE check was made before the wait ended, so it does not count
    assert d.check_labels[1].text().startswith("✓  Waited 7 days")
    assert d.check_labels[2].text().startswith("✗") and not d.delete_button.isEnabled()
    with Store(db) as st:                            # pretend the check was made after the wait
        st.db.execute("UPDATE verifications SET checked = ?", (later.strftime("%Y-%m-%d %H:%M:%S"),))
        st.commit()
    d.load(d.scan_id)
    assert all(lab.text().startswith("✓") for lab in d.check_labels)
    assert not d.delete_button.isEnabled()           # the box is not ticked yet
    d.understand.setChecked(True)
    assert d.delete_button.isEnabled()

    d.confirm = lambda title, text: False
    d.delete_button.click()
    assert len(files(tmp_path / "_q")) == 4            # cancelled: nothing deleted

    kept_before = files(data)
    d.confirm = lambda title, text: True
    d.delete_button.click()
    wait_for(qapp, lambda: d.thread is None)
    assert d.result.text() == "Deleted 4 copies, freeing 10.21 MB."
    assert not (tmp_path / "_q").exists()             # emptied folders removed too
    assert files(data) == kept_before                 # kept copies untouched
    assert d.picker.count() == 0

    w.go(5)                                           # it can no longer be put back
    assert not w.quarantine.undo_button.isEnabled()
    assert "deleted them for good" in w.quarantine.result_title.text()


def test_smoke_test_of_a_built_app(qapp):
    from dupefinder.app import smoke
    assert smoke.run() == 0


def test_version_matches_pyproject():
    import re
    from dupefinder import __version__
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    text = open(os.path.join(root, "pyproject.toml"), encoding="utf-8").read()
    assert re.search(r'^version = "([^"]+)"', text, re.M).group(1) == __version__
