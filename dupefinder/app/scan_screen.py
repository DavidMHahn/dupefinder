"""Step 1: choose drives or folders and scan them. Scanning only reads files."""

import os

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QListWidget,
    QMessageBox, QProgressBar, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from ..common import fmt
from ..finder import write_report
from .worker import ScanWorker

ONE_MB = 1_000_000

STAGE_TEXT = {
    1: "Step 1 of 3: Finding files",
    3: "Step 2 of 3: Comparing the start of files that have the same size",
    4: "Step 3 of 3: Checking whole files that still match",
}


def heading(text, size=20):
    label = QLabel(text)
    label.setObjectName("heading")
    label.setStyleSheet(f"font-size: {size}px; font-weight: 600;")
    return label


def note(text):
    label = QLabel(text)
    label.setWordWrap(True)
    label.setObjectName("note")
    return label


class FolderList(QWidget):
    """A list of folders with Add and Remove buttons."""

    changed = Signal()

    def __init__(self, title, hint, add_text, dialog_title):
        super().__init__()
        self.dialog_title = dialog_title
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(heading(title, 15))
        layout.addWidget(note(hint))
        self.list = QListWidget()
        self.list.setMinimumHeight(72)
        self.list.setSelectionMode(QListWidget.ExtendedSelection)
        layout.addWidget(self.list)
        buttons = QHBoxLayout()
        self.add_button = QPushButton(add_text)
        self.remove_button = QPushButton("Remove")
        self.remove_button.setEnabled(False)
        buttons.addWidget(self.add_button)
        buttons.addWidget(self.remove_button)
        buttons.addStretch()
        layout.addLayout(buttons)
        self.add_button.clicked.connect(self._pick)
        self.remove_button.clicked.connect(self._remove)
        self.list.itemSelectionChanged.connect(
            lambda: self.remove_button.setEnabled(bool(self.list.selectedItems())))

    def folders(self):
        return [self.list.item(i).text() for i in range(self.list.count())]

    def add(self, folder):
        folder = os.path.normpath(os.path.abspath(folder))
        if folder not in self.folders():
            self.list.addItem(folder)
            self.changed.emit()

    def _pick(self):
        folder = QFileDialog.getExistingDirectory(self, self.dialog_title)
        if folder:
            self.add(folder)

    def _remove(self):
        for item in self.list.selectedItems():
            self.list.takeItem(self.list.row(item))
        self.changed.emit()

    def setEnabled(self, on):            # noqa: N802 (Qt naming)
        self.add_button.setEnabled(on)
        self.remove_button.setEnabled(on and bool(self.list.selectedItems()))
        self.list.setEnabled(on)


class ScanScreen(QWidget):
    """Emits scanned(result, scan_id) when a scan finishes."""

    scanned = Signal(object, int)

    def __init__(self, db_path=None):
        super().__init__()
        self.db_path = db_path
        self.thread = None
        self.worker = None
        self.result = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        layout.addWidget(heading("Scan for duplicates"))
        layout.addWidget(note("Scanning only reads your files. Nothing is changed, moved or deleted. "
                              "You will review everything before any file is touched."))

        self.roots = FolderList("Drives and folders to scan",
                                "Add one or more. Files are compared across all of them, "
                                "so two drives can be checked against each other.",
                                "Add drive or folder…", "Choose a drive or folder to scan")
        layout.addWidget(self.roots)

        self.excludes = FolderList("Folders to skip (optional)",
                                   "For example a backup tool's folder, which should never be cleaned.",
                                   "Add folder to skip…", "Choose a folder to skip")
        layout.addWidget(self.excludes)

        self.skip_small = QCheckBox("Skip files smaller than 1 MB (faster; small files rarely save much space)")
        layout.addWidget(self.skip_small)

        row = QHBoxLayout()
        self.start_button = QPushButton("Start scan")
        self.start_button.setObjectName("primary")
        self.start_button.setEnabled(False)
        self.stop_button = QPushButton("Stop")
        self.stop_button.setEnabled(False)
        row.addWidget(self.start_button)
        row.addWidget(self.stop_button)
        row.addStretch()
        layout.addLayout(row)

        self.stage = QLabel("")
        self.bar = QProgressBar()
        self.bar.setVisible(False)
        layout.addWidget(self.stage)
        layout.addWidget(self.bar)

        self.results = self._results_panel()
        self.results.setVisible(False)
        layout.addWidget(self.results)
        layout.addStretch()

        self.roots.changed.connect(self._update_start)
        self.start_button.clicked.connect(self.start)
        self.stop_button.clicked.connect(self.stop)

    # ------------------------------------------------------------ layout helpers
    def _results_panel(self):
        panel = QFrame()
        panel.setObjectName("results")
        panel.setFrameShape(QFrame.StyledPanel)
        grid = QGridLayout(panel)
        grid.setContentsMargins(16, 12, 16, 12)
        self.title = heading("Scan complete", 15)
        grid.addWidget(self.title, 0, 0, 1, 3)
        self.big = {}
        for col, key in enumerate(("space", "groups", "files")):
            value = QLabel("")
            value.setStyleSheet("font-size: 22px; font-weight: 600;")
            caption = QLabel({"space": "could be freed", "groups": "groups of identical files",
                              "files": "files involved"}[key])
            caption.setObjectName("note")
            grid.addWidget(value, 1, col)
            grid.addWidget(caption, 2, col)
            self.big[key] = value
        self.detail = note("")
        grid.addWidget(self.detail, 3, 0, 1, 3)
        buttons = QHBoxLayout()
        self.export_button = QPushButton("Save report as CSV…")
        self.next_button = QPushButton("Review duplicates  →")
        self.next_button.setObjectName("primary")
        self.next_button.setEnabled(False)
        self.next_button.setToolTip("The Review screen comes next.")
        buttons.addWidget(self.export_button)
        buttons.addStretch()
        buttons.addWidget(self.next_button)
        grid.addLayout(buttons, 4, 0, 1, 3)
        self.export_button.clicked.connect(self.export_csv)
        panel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        return panel

    def _update_start(self):
        self.start_button.setEnabled(bool(self.roots.folders()) and self.thread is None)

    def _busy(self, on):
        self.roots.setEnabled(not on)
        self.excludes.setEnabled(not on)
        self.skip_small.setEnabled(not on)
        self.stop_button.setEnabled(on)
        self.start_button.setEnabled(not on and bool(self.roots.folders()))
        self.bar.setVisible(on)

    # ------------------------------------------------------------ scanning
    def start(self):
        missing = [f for f in self.roots.folders() if not os.path.isdir(f)]
        if missing:
            QMessageBox.warning(self, "Folder not found",
                                "These can't be found. Is the drive plugged in?\n\n" + "\n".join(missing))
            return
        self.results.setVisible(False)
        self.result = None
        self.worker = ScanWorker(self.roots.folders(), self.excludes.folders(),
                                 ONE_MB if self.skip_small.isChecked() else 1, self.db_path)
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
        self.stage.setText("Starting…")
        self.bar.setRange(0, 0)
        self._busy(True)
        self.thread.start()

    def stop(self):
        if self.worker:
            self.worker.stop()
            self.stop_button.setEnabled(False)
            self.stage.setText("Stopping…")

    def _on_progress(self, stage, done, total):
        if total < 0:
            self.bar.setRange(0, 0)                         # busy: total not known yet
            self.stage.setText(f"{STAGE_TEXT[stage]}: {done:,} found so far")
        else:
            self.bar.setRange(0, max(total, 1))
            self.bar.setValue(done)
            self.stage.setText(f"{STAGE_TEXT[stage]}: {done:,} of {total:,}")

    def _on_finished(self, res, scan_id):
        self.result = res
        self.stage.setText("")
        self.big["space"].setText(fmt(res.wasted))
        self.big["groups"].setText(f"{len(res.groups):,}")
        self.big["files"].setText(f"{res.dup_files:,}")
        reused = f" {res.cache_hits:,} checks were reused from earlier scans." if res.cache_hits else ""
        self.detail.setText(
            f"Looked at {res.n_files:,} files ({fmt(res.n_bytes)}). Nothing was changed.{reused}")
        self.title.setText("Scan complete" if res.groups else "Scan complete: no duplicates found")
        self.export_button.setEnabled(bool(res.groups))
        self.results.setVisible(True)
        self.scanned.emit(res, scan_id)

    def _on_cancelled(self):
        self.stage.setText("Scan stopped. Work done so far is saved, so scanning again "
                           "will carry on from where it stopped.")

    def _on_failed(self, message):
        self.stage.setText("The scan could not finish.")
        QMessageBox.critical(self, "Scan failed", message)

    def _cleanup(self):
        self.thread.deleteLater()
        self.worker.deleteLater()
        self.thread = None
        self.worker = None
        self._busy(False)

    # ------------------------------------------------------------ export
    def export_csv(self, path=None):
        if not self.result:
            return
        if not path:
            path, _ = QFileDialog.getSaveFileName(self, "Save report", "duplicates.csv",
                                                  "CSV files (*.csv)")
        if path:
            write_report(self.result.groups, path)
        return path

