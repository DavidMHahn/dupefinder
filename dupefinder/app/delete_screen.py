"""Step 8: permanently delete the quarantined copies. The only screen that deletes.

Deleting is allowed only when the move finished and was not undone, the wait
is over, and a SAFE check was made after the wait and within the last day.
The person must also tick a box and confirm. Only files the moves log lists
are deleted, each after checking its kept copy is still there.
"""

from datetime import datetime

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QHBoxLayout, QLabel, QMessageBox, QProgressBar, QPushButton, QVBoxLayout,
    QWidget,
)

from .. import deleter
from ..common import fmt
from ..store import Store
from .scan_screen import heading, note
from .wait_screen import open_runs, run_label
from .worker import DeleteWorker, VerifyWorker, default_db_path

PASS, FAIL = "✓", "✗"


class DeleteScreen(QWidget):
    deleted = Signal()

    def __init__(self, db_path=None):
        super().__init__()
        self.db_path = db_path or default_db_path()
        self.scan_id = None
        self.runs = []
        self.passed = False
        self.thread = None
        self.worker = None
        self.now = datetime.now            # replaced in tests

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        layout.addWidget(heading("Delete the quarantine for good"))
        layout.addWidget(note(
            "This permanently deletes the extra copies in quarantine, freeing their space. Your kept "
            "copies are not touched. Only copies whose kept copy is still there are deleted; anything "
            "else stays in quarantine and is listed."))

        row = QHBoxLayout()
        row.addWidget(QLabel("Quarantine run:"))
        self.picker = QComboBox()
        self.picker.setMinimumWidth(420)
        row.addWidget(self.picker, 1)
        layout.addLayout(row)

        layout.addWidget(heading("Before deleting", 15))
        self.check_labels = [QLabel("") for _ in range(3)]
        for lab in self.check_labels:
            lab.setWordWrap(True)
            layout.addWidget(lab)
        crow = QHBoxLayout()
        self.verify_button = QPushButton("Check the quarantine now")
        crow.addWidget(self.verify_button)
        crow.addStretch()
        layout.addLayout(crow)

        self.understand = QCheckBox("")
        layout.addWidget(self.understand)

        drow = QHBoxLayout()
        self.delete_button = QPushButton("Delete permanently")
        self.delete_button.setObjectName("primary")
        self.delete_button.setEnabled(False)
        self.stop_button = QPushButton("Stop")
        self.stop_button.setEnabled(False)
        drow.addWidget(self.delete_button)
        drow.addWidget(self.stop_button)
        drow.addStretch()
        layout.addLayout(drow)

        self.stage = QLabel("")
        self.stage.setWordWrap(True)
        self.bar = QProgressBar()
        self.bar.setVisible(False)
        layout.addWidget(self.stage)
        layout.addWidget(self.bar)
        self.result = QLabel("")
        self.result.setWordWrap(True)
        self.result.setStyleSheet("font-size: 15px; font-weight: 600;")
        layout.addWidget(self.result)
        self.result_detail = note("")
        layout.addWidget(self.result_detail)
        layout.addStretch()

        self.picker.currentIndexChanged.connect(self._refresh)
        self.understand.toggled.connect(self._update_button)
        self.verify_button.clicked.connect(self.check_now)
        self.delete_button.clicked.connect(self.delete)
        self.stop_button.clicked.connect(self.stop)

    # ------------------------------------------------------------ dialogs (replaced in tests)
    def confirm(self, title, text):
        box = QMessageBox(QMessageBox.Warning, title, text, QMessageBox.Yes | QMessageBox.Cancel, self)
        box.setDefaultButton(QMessageBox.Cancel)
        return box.exec() == QMessageBox.Yes

    def error(self, title, text):
        QMessageBox.critical(self, title, text)

    # ------------------------------------------------------------ loading
    def load(self, scan_id):
        if self.thread is not None:
            return
        self.scan_id = scan_id
        self.runs = open_runs(self.db_path, scan_id) if scan_id is not None else []
        self.picker.blockSignals(True)
        self.picker.clear()
        for r in self.runs:
            self.picker.addItem(run_label(r), r["id"])
        self.picker.blockSignals(False)
        self._refresh()

    def run(self):
        i = self.picker.currentIndex()
        return self.runs[i] if 0 <= i < len(self.runs) else None

    def _refresh(self):
        run = self.run()
        self.understand.setChecked(False)
        if run is None:
            for lab in self.check_labels:
                lab.setText("")
            self.check_labels[0].setText("Nothing is in quarantine for this scan.")
            self.passed = False
            self.verify_button.setEnabled(False)
            self.understand.setVisible(False)
            self._update_button()
            return
        with Store(self.db_path) as st:
            last = st.latest_verification(run["id"])
        results = deleter.checks(run, last, self.now())
        for lab, (ok, text) in zip(self.check_labels, results):
            lab.setText(f"{PASS if ok else FAIL}  {text}")
            lab.setStyleSheet("" if ok else "color: #c62828;")
        self.passed = all(ok for ok, _ in results)
        wait_ok = results[1][0]
        self.verify_button.setEnabled(wait_ok and self.thread is None)
        self.understand.setText(f"I understand that {run['moved']:,} copies ({fmt(run['freed'] or 0)}) "
                                "will be permanently deleted from quarantine. Their kept copies stay.")
        self.understand.setVisible(self.passed)
        self._update_button()

    def _update_button(self):
        self.delete_button.setEnabled(self.passed and self.understand.isChecked() and self.thread is None)

    # ------------------------------------------------------------ check, then delete
    def check_now(self):
        run = self.run()
        if run is None or self.thread is not None:
            return
        self.worker = VerifyWorker(run["id"], run["log_path"], self.db_path)
        self.worker.finished.connect(self._on_checked)
        self.worker.cancelled.connect(self._on_check_stopped)
        self.worker.failed.connect(self._on_failed)
        self._run([self.worker.finished, self.worker.cancelled, self.worker.failed], "Checking…")

    def delete(self):
        run = self.run()
        if run is None or not self.delete_button.isEnabled():
            return
        if not self.confirm("Delete permanently",
                            f"Permanently delete {run['moved']:,} copies ({fmt(run['freed'] or 0)}) from "
                            "quarantine?\n\nThis cannot be undone. Kept copies are not touched."):
            return
        with Store(self.db_path) as st:
            qroots = st.quarantine_folders(run["dry_run_id"])
        self.worker = DeleteWorker(run, qroots, self.db_path)
        self.worker.finished.connect(self._on_deleted)
        self.worker.failed.connect(self._on_failed)
        self._run([self.worker.finished, self.worker.failed], "Deleting…")
        self.stop_button.setEnabled(True)

    def stop(self):
        if self.worker:
            self.worker.stop()
            self.stop_button.setEnabled(False)

    def _run(self, ends, message):
        self.thread = QThread(self)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self._on_progress)
        for sig in ends:
            sig.connect(self.thread.quit)
        self.thread.finished.connect(self._cleanup)
        self.bar.setRange(0, 0)
        self.bar.setVisible(True)
        self.stage.setText(message)
        self.result.setText("")
        self.result_detail.setText("")
        self.delete_button.setEnabled(False)
        self.verify_button.setEnabled(False)
        self.picker.setEnabled(False)
        self.thread.start()

    def _on_progress(self, done, total):
        self.bar.setRange(0, max(total, 1))
        self.bar.setValue(done)
        self.stage.setText(f"{done:,} of {total:,}")

    def _on_checked(self, verdict):
        self.stage.setText("Check complete: SAFE." if verdict.safe else
                           "Check complete: NOT SAFE. See step 6 for the problems; nothing can be deleted.")

    def _on_check_stopped(self):
        self.stage.setText("Check stopped.")

    def _on_deleted(self, res):
        self.stage.setText("")
        stopped = " You stopped it part-way." if res.stopped else ""
        self.result.setText(f"Deleted {res.deleted:,} copies, freeing {fmt(res.freed)}.{stopped}")
        detail = f"Log: {res.log_path}"
        if res.kept:
            detail = (f"{len(res.kept):,} copies were left in quarantine because a last check failed "
                      f"(listed in the log).\n" + detail)
        self.result_detail.setText(detail)
        self.deleted.emit()

    def _on_failed(self, message):
        self.stage.setText("Stopped with an error. The log lists everything that was done.")
        self.error("Error", message)

    def _cleanup(self):
        self.thread.deleteLater()
        self.worker.deleteLater()
        self.thread = None
        self.worker = None
        self.bar.setVisible(False)
        self.stop_button.setEnabled(False)
        self.picker.setEnabled(True)
        current = self.run()
        self.load(self.scan_id)
        if current is not None:
            idx = self.picker.findData(current["id"])
            if idx >= 0:
                self.picker.setCurrentIndex(idx)
