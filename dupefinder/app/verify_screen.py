"""Step 6: check the quarantine. READ-ONLY.

For every copy a quarantine run moved, it re-reads the quarantined copy and
the kept copy and confirms they are still identical. Only a SAFE result
means the quarantine folder could later be deleted.
"""

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QListWidget, QMessageBox, QProgressBar, QPushButton,
    QVBoxLayout, QWidget,
)

from ..common import fmt
from ..store import Store
from .scan_screen import heading, note
from .worker import VerifyWorker, default_db_path

SAFE_STYLE = "font-size: 22px; font-weight: 700; color: #1a7f37;"
NOT_SAFE_STYLE = "font-size: 22px; font-weight: 700; color: #c62828;"


class VerifyScreen(QWidget):
    next_requested = Signal()

    def __init__(self, db_path=None):
        super().__init__()
        self.db_path = db_path or default_db_path()
        self.scan_id = None
        self.runs = []
        self.verdict = None
        self.thread = None
        self.worker = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        layout.addWidget(heading("Check the quarantine"))
        layout.addWidget(note(
            "This re-reads every copy in quarantine and its kept copy, and confirms they are still "
            "identical. It only reads files. Run it now, and again just before deleting anything."))

        row = QHBoxLayout()
        row.addWidget(QLabel("Quarantine run:"))
        self.picker = QComboBox()
        self.picker.setMinimumWidth(420)
        row.addWidget(self.picker, 1)
        layout.addLayout(row)

        brow = QHBoxLayout()
        self.check_button = QPushButton("Check now")
        self.check_button.setObjectName("primary")
        self.check_button.setEnabled(False)
        self.stop_button = QPushButton("Stop")
        self.stop_button.setEnabled(False)
        brow.addWidget(self.check_button)
        brow.addWidget(self.stop_button)
        brow.addStretch()
        layout.addLayout(brow)

        self.stage = QLabel("")
        self.bar = QProgressBar()
        self.bar.setVisible(False)
        layout.addWidget(self.stage)
        layout.addWidget(self.bar)

        self.panel = QFrame()
        self.panel.setFrameShape(QFrame.StyledPanel)
        pl = QVBoxLayout(self.panel)
        pl.setContentsMargins(16, 12, 16, 12)
        self.verdict_label = QLabel("")
        self.detail = note("")
        self.problems = QListWidget()
        pl.addWidget(self.verdict_label)
        pl.addWidget(self.detail)
        pl.addWidget(self.problems, 1)
        self.panel.setVisible(False)
        self.layout_ = layout
        layout.addWidget(self.panel)
        self.spacer = QWidget()
        layout.addWidget(self.spacer, 1)

        buttons = QHBoxLayout()
        buttons.addStretch()
        self.next_button = QPushButton("Wait before deleting  →")
        self.next_button.setObjectName("primary")
        self.next_button.setEnabled(False)
        self.next_button.setToolTip("The Wait screen comes next.")
        buttons.addWidget(self.next_button)
        layout.addLayout(buttons)

        self.picker.currentIndexChanged.connect(self._run_chosen)
        self.check_button.clicked.connect(self.start)
        self.stop_button.clicked.connect(self.stop)
        self.next_button.clicked.connect(self.next_requested)

    # ------------------------------------------------------------ loading
    def load(self, scan_id):
        if scan_id is None or self.thread is not None:
            return
        self.scan_id = scan_id
        with Store(self.db_path) as st:
            self.runs = [r for r in st.quarantine_runs(scan_id) if not r["undone"] and r["moved"] != 0]
        self.picker.blockSignals(True)
        self.picker.clear()
        for r in self.runs:
            moved = "unfinished" if r["moved"] is None else f"moved {r['moved']:,} copies, {fmt(r['freed'] or 0)}"
            self.picker.addItem(f"{r['started']}  ·  {moved}", r["id"])
        self.picker.blockSignals(False)
        self._run_chosen()

    def run(self):
        i = self.picker.currentIndex()
        return self.runs[i] if 0 <= i < len(self.runs) else None

    def _run_chosen(self):
        run = self.run()
        self.check_button.setEnabled(run is not None and self.thread is None)
        if run is None:
            self.stage.setText("Nothing is in quarantine for this scan yet (step 5).")
            self._show(None, None)
            return
        with Store(self.db_path) as st:
            last = st.latest_verification(run["id"])
        if last:
            self.stage.setText("")
            self._show(*last)
        else:
            self.stage.setText("Not checked yet.")
            self._show(None, None)

    # ------------------------------------------------------------ checking
    def start(self):
        run = self.run()
        if run is None or self.thread is not None:
            return
        self.worker = VerifyWorker(run["id"], run["log_path"], self.db_path)
        self.thread = QThread(self)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_finished)
        self.worker.cancelled.connect(self._on_cancelled)
        self.worker.failed.connect(self._on_failed)
        for sig in (self.worker.finished, self.worker.cancelled, self.worker.failed):
            sig.connect(self.thread.quit)
        self.thread.finished.connect(self._cleanup)
        self.bar.setRange(0, 0)
        self.bar.setVisible(True)
        self.check_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.picker.setEnabled(False)
        self.stage.setText("Checking…")
        self.thread.start()

    def stop(self):
        if self.worker:
            self.worker.stop()
            self.stop_button.setEnabled(False)

    def _on_progress(self, done, total):
        self.bar.setRange(0, max(total, 1))
        self.bar.setValue(done)
        self.stage.setText(f"Checking: {done:,} of {total:,} copies")

    def _on_finished(self, verdict):
        self.stage.setText("Check complete. Nothing was changed.")
        with Store(self.db_path) as st:
            last = st.latest_verification(self.run()["id"])
        self._show(*last)

    def _on_cancelled(self):
        self.stage.setText("Check stopped. Nothing was changed; run it again for a result.")

    def _on_failed(self, message):
        self.stage.setText("The check could not finish.")
        QMessageBox.critical(self, "Check failed", message)

    def _cleanup(self):
        self.thread.deleteLater()
        self.worker.deleteLater()
        self.thread = None
        self.worker = None
        self.bar.setVisible(False)
        self.stop_button.setEnabled(False)
        self.picker.setEnabled(True)
        self.check_button.setEnabled(self.run() is not None)

    # ------------------------------------------------------------ verdict
    def _show(self, checked, verdict):
        self.verdict = verdict
        self.panel.setVisible(verdict is not None)
        self.problems.clear()
        self.next_button.setEnabled(False)          # until the Wait screen exists
        if verdict is None:
            self.spacer.setVisible(True)
            return
        if verdict.safe:
            self.verdict_label.setText("SAFE")
            self.verdict_label.setStyleSheet(SAFE_STYLE)
            self.detail.setText(f"All {verdict.total:,} copies in quarantine have an identical kept copy "
                                f"(checked {checked}). Keep the quarantine for a while anyway, in case "
                                "something turns out to be missing.")
        else:
            self.verdict_label.setText("NOT SAFE to delete")
            self.verdict_label.setStyleSheet(NOT_SAFE_STYLE)
            kinds = "; ".join(f"{n:,} {k.lower()}" for k, n in sorted(verdict.summary().items()))
            self.detail.setText(f"{verdict.ok:,} of {verdict.total:,} copies have an identical kept copy "
                                f"(checked {checked}). Problems: {kinds}. Do not delete the quarantine; "
                                "look at the files below first.")
            self.problems.addItems(verdict.problems)
        has_list = bool(verdict.problems)
        self.problems.setVisible(has_list)
        self.spacer.setVisible(not has_list)                     # the list, if any, takes the space
        self.layout_.setStretchFactor(self.panel, 1 if has_list else 0)
