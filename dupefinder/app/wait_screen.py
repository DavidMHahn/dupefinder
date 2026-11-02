"""Step 7: live with the result for a while before deleting anything.

Nothing happens on this screen except choosing how long to wait. The
quarantine only takes space; Put everything back (step 5) still works.
"""

from datetime import datetime

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from .. import deleter
from ..common import fmt
from ..store import Store
from .scan_screen import heading, note
from .worker import default_db_path

WAIT_CHOICES = [7, 14, 30]


def open_runs(db_path, scan_id):
    """Quarantine runs that still have copies in quarantine, newest first."""
    with Store(db_path) as st:
        return [r for r in st.quarantine_runs(scan_id)
                if not r["undone"] and not r["deleted"] and r["moved"]]


def run_label(r):
    return f"{r['started']}  ·  moved {r['moved']:,} copies, {fmt(r['freed'] or 0)}"


class WaitScreen(QWidget):
    next_requested = Signal()

    def __init__(self, db_path=None):
        super().__init__()
        self.db_path = db_path or default_db_path()
        self.scan_id = None
        self.runs = []
        self.now = datetime.now            # replaced in tests

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        layout.addWidget(heading("Wait before deleting"))
        layout.addWidget(note(
            "Use your computer normally for a while. If a file you need turns out to be missing, "
            "Put everything back on step 5 still works, or copy it back from the quarantine folder. "
            "Your kept copies are untouched; the quarantine only takes up space until it is deleted."))

        row = QHBoxLayout()
        row.addWidget(QLabel("Quarantine run:"))
        self.picker = QComboBox()
        self.picker.setMinimumWidth(420)
        row.addWidget(self.picker, 1)
        layout.addLayout(row)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Wait at least:"))
        self.days = QComboBox()
        for d in WAIT_CHOICES:
            self.days.addItem(f"{d} days", d)
        row2.addWidget(self.days)
        row2.addStretch()
        layout.addLayout(row2)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("font-size: 18px; font-weight: 600;")
        layout.addWidget(self.status)
        self.detail = note("")
        layout.addWidget(self.detail)
        layout.addStretch()

        buttons = QHBoxLayout()
        buttons.addStretch()
        self.next_button = QPushButton("Delete the quarantine  →")
        self.next_button.setObjectName("primary")
        self.next_button.setEnabled(False)
        buttons.addWidget(self.next_button)
        layout.addLayout(buttons)

        self.picker.currentIndexChanged.connect(self._refresh)
        self.days.currentIndexChanged.connect(self._days_changed)
        self.next_button.clicked.connect(self.next_requested)

    def load(self, scan_id):
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

    def _days_changed(self):
        run = self.run()
        if run is None:
            return
        run["wait_days"] = self.days.currentData()
        with Store(self.db_path) as st:
            st.set_wait(run["id"], run["wait_days"])
        self._refresh()

    def _refresh(self):
        run = self.run()
        self.days.setEnabled(run is not None)
        if run is None:
            self.status.setText("Nothing is waiting in quarantine for this scan.")
            self.detail.setText("")
            self.next_button.setEnabled(False)
            return
        self.days.blockSignals(True)
        idx = self.days.findData(run["wait_days"])
        if idx < 0:
            self.days.addItem(f"{run['wait_days']} days", run["wait_days"])
            idx = self.days.count() - 1
        self.days.setCurrentIndex(idx)
        self.days.blockSignals(False)
        ends = deleter.wait_ends(run)
        left = ends - self.now()
        if left.total_seconds() > 0:
            days = left.days + (1 if left.seconds else 0)
            self.status.setText(f"{days} day{'s' if days != 1 else ''} to go")
            self.detail.setText(f"Deleting opens on {ends:%A, %B %d at %I:%M %p}. Come back then; "
                                "you will be asked to check the quarantine once more first.")
            self.next_button.setEnabled(False)
        else:
            self.status.setText("The wait is over")
            self.detail.setText(f"It ended on {ends:%A, %B %d}. If nothing turned out to be missing, "
                                "you can delete the quarantine after one more check.")
            self.next_button.setEnabled(True)
