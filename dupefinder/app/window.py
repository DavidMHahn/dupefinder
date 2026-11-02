"""The main window: the eight steps on the left, the current step on the right."""

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow,
    QStackedWidget, QVBoxLayout, QWidget,
)

from .. import __version__
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

BUILT_STEPS = 2          # steps that have a screen so far

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
        self.pages.addWidget(self.scan)
        self.pages.addWidget(self.review)
        self.scan.next_button.clicked.connect(lambda: self.go(2))
        self.scan.scanned.connect(lambda res, scan_id: self._scanned(scan_id))
        self.steps.currentRowChanged.connect(lambda row: self.pages.setCurrentIndex(row))

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
        self._set_enabled(2 if self.review.scans.count() else 1)
        self.steps.setCurrentRow(0)

    def _set_enabled(self, upto):
        """Steps 1..upto can be opened; the rest are greyed out."""
        for i in range(self.steps.count()):
            item = self.steps.item(i)
            on = Qt.ItemIsEnabled | Qt.ItemIsSelectable
            item.setFlags(item.flags() | on if i < upto else item.flags() & ~on)

    def _scanned(self, scan_id):
        self.review.scan_id = None
        self.review.refresh_scans(select_id=scan_id)
        self._set_enabled(2)

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
