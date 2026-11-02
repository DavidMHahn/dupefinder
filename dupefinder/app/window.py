"""The main window: the eight steps on the left, the current step on the right."""

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow,
    QStackedWidget, QVBoxLayout, QWidget,
)

from .. import __version__
from .dryrun_screen import DryRunScreen
from .keepers_screen import KeepersScreen
from .review_screen import ReviewScreen
from .scan_screen import ScanScreen
from .worker import default_db_path

STEPS = [
    ("Scan", "Find duplicate files. Only reads."),
    ("Review groups", "See what was found, biggest first."),
    ("Choose keepers", "Decide which copy stays."),
    ("Dry run", "Preview every move. Changes nothing."),
    ("Quarantine", "Move extra copies aside. Can be undone."),
    ("Verify", "Check every kept copy is still there."),
    ("Wait", "Live with it for a week or two."),
    ("Delete", "Empty the quarantine for good."),
]

BUILT_STEPS = 4          # steps that have a screen so far

STYLE = """
QListWidget#steps { border: none; font-size: 14px; }
QListWidget#steps::item { padding: 8px 10px; }
QLabel#note { color: palette(placeholder-text); }
QPushButton { padding: 6px 14px; }
QPushButton#primary { font-weight: 600; }
"""


class MainWindow(QMainWindow):
    def __init__(self, db_path=None):
        super().__init__()
        self.setWindowTitle(f"dupefinder {__version__}")
        self.resize(980, 720)

        self.steps = QListWidget()
        self.steps.setObjectName("steps")
        self.steps.setFixedWidth(220)
        for i, (name, tip) in enumerate(STEPS, 1):
            item = QListWidgetItem(f"{i}   {name}")
            item.setToolTip(tip if i <= BUILT_STEPS else f"{tip} (coming next)")
            self.steps.addItem(item)

        db_path = db_path or default_db_path()
        self.pages = QStackedWidget()
        self.scan = ScanScreen(db_path)
        self.review = ReviewScreen(db_path)
        self.keepers = KeepersScreen(db_path)
        self.dryrun = DryRunScreen(db_path)
        for page in (self.scan, self.review, self.keepers, self.dryrun):
            self.pages.addWidget(page)
        self.scan.next_button.clicked.connect(lambda: self.go(2))
        self.scan.scanned.connect(lambda res, scan_id: self._scanned(scan_id))
        self.review.loaded.connect(lambda has_groups: self._update_steps())
        self.review.next_requested.connect(lambda: self.go(3))
        self.keepers.next_requested.connect(lambda: self.go(4))
        self.steps.currentRowChanged.connect(self._show_page)

        side = QVBoxLayout()
        side.setContentsMargins(12, 20, 0, 12)
        title = QLabel("dupefinder")
        title.setStyleSheet("font-size: 18px; font-weight: 700; padding-left: 10px;")
        side.addWidget(title)
        motto = QLabel("Nothing is deleted until a\nverified quarantine has waited.")
        motto.setObjectName("note")
        motto.setStyleSheet("padding-left: 10px;")
        side.addWidget(motto)
        side.addSpacing(8)
        side.addWidget(self.steps)

        root = QWidget()
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(side)
        layout.addWidget(self.pages, 1)
        self.setCentralWidget(root)
        self.review.refresh_scans()
        self._update_steps()
        self.steps.setCurrentRow(0)

    def _show_page(self, row):
        if row == 2:                    # Choose keepers works on the scan picked in Review
            self.keepers.load(self.review.scan_id)
        if row == 3:                    # the dry run always uses the latest keeper choices
            self.dryrun.load(self.review.scan_id)
        self.pages.setCurrentIndex(row)

    def _update_steps(self):
        """Scan is always open; Review once a scan is saved; Choose keepers and Dry run once it
        found duplicates."""
        upto = 1
        if self.review.scans.count():
            upto = 4 if self.review.sets else 2
        self._set_enabled(upto)

    def _set_enabled(self, upto):
        """Steps 1..upto can be opened; the rest are greyed out."""
        for i in range(self.steps.count()):
            item = self.steps.item(i)
            on = Qt.ItemIsEnabled | Qt.ItemIsSelectable
            item.setFlags(item.flags() | on if i < upto else item.flags() & ~on)

    def _scanned(self, scan_id):
        self.review.scan_id = None
        self.review.refresh_scans(select_id=scan_id)
        self._update_steps()

    def go(self, step):
        self.steps.setCurrentRow(step - 1)

    def enabled_steps(self):
        return [self.steps.item(i).text() for i in range(self.steps.count())
                if self.steps.item(i).flags() & Qt.ItemIsEnabled]


def run(argv=None):
    app = QApplication.instance() or QApplication(sys.argv if argv is None else argv)
    app.setApplicationName("dupefinder")
    app.setStyleSheet(STYLE)
    window = MainWindow()
    window.show()
    return app.exec()
