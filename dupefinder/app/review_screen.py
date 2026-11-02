"""Step 2: see what the scan found, gathered by folder, biggest saving first.

Nothing on this screen changes a file.
"""

import os

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton,
    QSplitter, QTableWidget, QTableWidgetItem, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ..common import fmt
from ..review import folder_sets
from ..store import Store
from .scan_screen import heading, note
from .worker import default_db_path


def show_in_explorer(path):
    """Open the folder holding path, with the file selected on Windows. Read-only."""
    if not path:
        return
    if os.name == "nt" and os.path.exists(path):
        import subprocess
        subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
    else:
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path)))


class NumberItem(QTableWidgetItem):
    """A table cell that shows text but sorts by a number."""

    def __init__(self, text, value):
        super().__init__(text)
        self.value = value
        self.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

    def __lt__(self, other):
        return self.value < getattr(other, "value", 0)


class ReviewScreen(QWidget):
    """Shows one scan's duplicates. Emits next_requested when the person moves on."""

    next_requested = Signal()
    loaded = Signal(bool)       # a scan was shown; True if it has duplicates

    def __init__(self, db_path=None):
        super().__init__()
        self.db_path = db_path or default_db_path()
        self.sets = []          # all FolderSets of the current scan
        self.shown = []         # the ones the table shows (after the filter)
        self.scan_id = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)
        layout.addWidget(heading("Review what was found"))
        layout.addWidget(note("Duplicates are grouped by the folders that hold the copies, biggest "
                              "saving first. Nothing has been changed. Next you will choose which "
                              "copy to keep."))

        row = QHBoxLayout()
        row.addWidget(QLabel("Scan:"))
        self.scans = QComboBox()
        self.scans.setMinimumWidth(360)
        row.addWidget(self.scans, 1)
        row.addSpacing(16)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter by folder or file name…")
        self.filter.setClearButtonEnabled(True)
        row.addWidget(self.filter, 1)
        layout.addLayout(row)

        self.summary = QLabel("")
        self.summary.setStyleSheet("font-weight: 600;")
        layout.addWidget(self.summary)

        split = QSplitter(Qt.Vertical)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Folders holding the copies", "Groups", "Files", "Could free"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setWordWrap(True)
        self.table.setTextElideMode(Qt.ElideMiddle)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for col in (1, 2, 3):
            header.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        header.setSortIndicator(3, Qt.DescendingOrder)       # biggest saving first
        split.addWidget(self.table)

        lower = QWidget()
        lower_layout = QVBoxLayout(lower)
        lower_layout.setContentsMargins(0, 8, 0, 0)
        self.detail_title = heading("Pick a row above to see its files", 14)
        lower_layout.addWidget(self.detail_title)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels(["Identical files", "Size"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tree.setTextElideMode(Qt.ElideMiddle)
        lower_layout.addWidget(self.tree)
        split.addWidget(lower)
        split.setSizes([300, 300])
        layout.addWidget(split, 1)

        buttons = QHBoxLayout()
        self.open_button = QPushButton("Show in File Explorer")
        self.open_button.setEnabled(False)
        buttons.addWidget(self.open_button)
        buttons.addStretch()
        self.next_button = QPushButton("Choose which copies to keep  →")
        self.next_button.setObjectName("primary")
        self.next_button.setEnabled(False)
        buttons.addWidget(self.next_button)
        layout.addLayout(buttons)

        self.scans.currentIndexChanged.connect(self._scan_chosen)
        self.filter.textChanged.connect(self._fill_table)
        self.table.itemSelectionChanged.connect(self._fill_tree)
        self.tree.itemSelectionChanged.connect(
            lambda: self.open_button.setEnabled(self._selected_path() is not None))
        self.tree.itemDoubleClicked.connect(lambda *_: self.show_in_explorer())
        self.open_button.clicked.connect(self.show_in_explorer)
        self.next_button.clicked.connect(self.next_requested)

    # ------------------------------------------------------------ loading
    def refresh_scans(self, select_id=None):
        """Fill the scan picker from the database, newest first."""
        self.scans.blockSignals(True)
        self.scans.clear()
        if os.path.exists(self.db_path):
            with Store(self.db_path) as st:
                for s in st.list_scans():
                    where = ", ".join(s["roots"])
                    label = f"{s['finished'] or s['started']}  ·  {where}  ·  {fmt(s['wasted'] or 0)}"
                    self.scans.addItem(label, s["id"])
        self.scans.blockSignals(False)
        if self.scans.count():
            idx = self.scans.findData(select_id) if select_id is not None else 0
            self.scans.setCurrentIndex(max(idx, 0))
            self._scan_chosen()
        else:
            self.show_groups([])

    def _scan_chosen(self):
        scan_id = self.scans.currentData()
        if scan_id is None or scan_id == self.scan_id:
            return
        with Store(self.db_path) as st:
            groups = st.load_groups(scan_id)
        self.scan_id = scan_id
        self.show_groups(groups)

    def show_groups(self, groups):
        self.sets = folder_sets(groups)
        total = sum(fs.wasted for fs in self.sets)
        files = sum(fs.files for fs in self.sets)
        self.summary.setText(
            f"{fmt(total)} could be freed: {len(groups):,} groups, {files:,} files, "
            f"in {len(self.sets):,} sets of folders" if groups else "No duplicates in this scan.")
        self._fill_table()
        self.next_button.setEnabled(bool(groups))
        self.loaded.emit(bool(groups))

    # ------------------------------------------------------------ table and tree
    def _fill_table(self):
        text = self.filter.text().strip()
        self.shown = [fs for fs in self.sets if not text or fs.matches(text)]
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(self.shown))
        for row, fs in enumerate(self.shown):
            label = "\n".join(fs.folders)
            if fs.within_one_folder:
                label += "\n(copies inside the same folder)"
            first = QTableWidgetItem(label)
            first.setToolTip(label)
            first.setData(Qt.UserRole, row)
            self.table.setItem(row, 0, first)
            self.table.setItem(row, 1, NumberItem(f"{len(fs.groups):,}", len(fs.groups)))
            self.table.setItem(row, 2, NumberItem(f"{fs.files:,}", fs.files))
            self.table.setItem(row, 3, NumberItem(fmt(fs.wasted), fs.wasted))
        self.table.resizeRowsToContents()
        self.table.setSortingEnabled(True)
        self.tree.clear()
        self.detail_title.setText("Pick a row above to see its files" if self.shown
                                  else "Nothing matches the filter" if text else "")
        if self.shown:
            self.table.clearSelection()
            self.table.selectRow(0)
            self._fill_tree()

    def selected_set(self):
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        item = self.table.item(rows[0].row(), 0)
        return self.shown[item.data(Qt.UserRole)]

    def _fill_tree(self):
        self.tree.clear()
        fs = self.selected_set()
        if fs is None:
            return
        n = len(fs.groups)
        self.detail_title.setText(f"{n:,} group{'s' if n != 1 else ''} of identical files "
                                  f"in these folders, {fmt(fs.wasted)} could be freed")
        for g in fs.groups:
            names = {os.path.basename(p) for p in g.paths}
            title = next(iter(names)) if len(names) == 1 else f"{len(names)} different names"
            top = QTreeWidgetItem([f"{title}  ·  {len(g.paths)} copies, {fmt(g.wasted)} extra",
                                   fmt(g.size)])
            for p in g.paths:
                child = QTreeWidgetItem([p, fmt(g.size)])
                child.setData(0, Qt.UserRole, p)
                child.setToolTip(0, p)
                top.addChild(child)
            self.tree.addTopLevelItem(top)
            top.setExpanded(True)

    def _selected_path(self):
        items = self.tree.selectedItems()
        return items[0].data(0, Qt.UserRole) if items else None

    def show_in_explorer(self):
        """Open the folder of the selected file. Read-only."""
        show_in_explorer(self._selected_path())
