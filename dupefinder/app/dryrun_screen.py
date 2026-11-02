"""Step 4: preview every move. READ-ONLY: this screen never moves a file.

Each drive gets a quarantine folder (changeable). Running the dry run checks
every copy the keeper plan would move, and saves the result so the Quarantine
step carries out exactly what was previewed.
"""

import os

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QProgressBar, QPushButton, QTableView, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from .. import dryrun, keepers
from ..common import fmt
from ..store import Store
from .review_screen import show_in_explorer
from .scan_screen import heading, note
from .worker import DryRunWorker, default_db_path

SHOW = ["Everything", "Would move", "Skipped"]


class MovesModel(QAbstractTableModel):
    HEADERS = ["What happens", "Copy", "Kept copy", "Size"]

    def __init__(self):
        super().__init__()
        self.moves = []

    def set_moves(self, moves):
        self.beginResetModel()
        self.moves = list(moves)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):             # noqa: N802 (Qt naming)
        return 0 if parent.isValid() else len(self.moves)

    def columnCount(self, parent=QModelIndex()):          # noqa: N802
        return 4

    def headerData(self, section, orientation, role=Qt.DisplayRole):   # noqa: N802
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.HEADERS[section]
        return None

    def data(self, index, role=Qt.DisplayRole):
        m = self.moves[index.row()]
        col = index.column()
        if role == Qt.DisplayRole:
            if col == 0:
                return "Would move" if m.would_move else m.status.replace("skipped: ", "Skipped: ")
            return [None, m.original, m.kept, fmt(m.size)][col]
        if role == Qt.ToolTipRole and col in (1, 2):
            return (m.original if col == 1 else m.kept) + (f"\n→ {m.dest}" if m.dest and col == 1 else "")
        if role == Qt.UserRole:                           # for sorting and filtering
            return [m.status, m.original.lower(), m.kept.lower(), m.size][col]
        if role == Qt.TextAlignmentRole and col == 3:
            return int(Qt.AlignRight | Qt.AlignVCenter)
        return None


class MovesFilter(QSortFilterProxyModel):
    def __init__(self):
        super().__init__()
        self.mode = 0
        self.text = ""
        self.setSortRole(Qt.UserRole)

    def set(self, show=None, text=None):
        new_api = hasattr(self, "beginFilterChange")      # Qt 6.10+; invalidateFilter is deprecated
        if new_api:
            self.beginFilterChange()
        if show is not None:
            self.mode = show
        if text is not None:
            self.text = text.strip().lower()
        if new_api:
            self.endFilterChange()
        else:
            self.invalidateFilter()

    def filterAcceptsRow(self, row, parent):              # noqa: N802
        m = self.sourceModel().moves[row]
        if self.mode == 1 and not m.would_move or self.mode == 2 and m.would_move:
            return False
        return not self.text or self.text in m.original.lower() or self.text in m.kept.lower()


class DryRunScreen(QWidget):
    next_requested = Signal()

    def __init__(self, db_path=None):
        super().__init__()
        self.db_path = db_path or default_db_path()
        self.scan_id = None
        self.plans = []
        self.quarantines = {}            # volume -> folder
        self.dry = None
        self.thread = None
        self.worker = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)
        layout.addWidget(heading("Preview the moves (dry run)"))
        layout.addWidget(note("This checks every copy that would go to quarantine, exactly as the next "
                              "step will before it moves anything. Nothing is moved here. Extra copies "
                              "are moved, never deleted, to a quarantine folder on the same drive, so "
                              "moving is instant and can be undone."))

        layout.addWidget(heading("Quarantine folders", 15))
        self.qtable = QTableWidget(0, 3)
        self.qtable.setHorizontalHeaderLabels(["Drive", "Quarantine folder", "Copies to move"])
        self.qtable.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.qtable.setSelectionMode(QAbstractItemView.SingleSelection)
        self.qtable.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.qtable.verticalHeader().setVisible(False)
        qh = self.qtable.horizontalHeader()
        qh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        qh.setSectionResizeMode(1, QHeaderView.Stretch)
        qh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.qtable.setMaximumHeight(110)
        layout.addWidget(self.qtable)

        row = QHBoxLayout()
        self.change_button = QPushButton("Change folder…")
        self.change_button.setEnabled(False)
        self.run_button = QPushButton("Run the dry run")
        self.run_button.setObjectName("primary")
        self.run_button.setEnabled(False)
        row.addWidget(self.change_button)
        row.addStretch()
        row.addWidget(self.run_button)
        layout.addLayout(row)

        self.stage = QLabel("")
        self.bar = QProgressBar()
        self.bar.setVisible(False)
        layout.addWidget(self.stage)
        layout.addWidget(self.bar)

        self.summary = QLabel("")
        self.summary.setStyleSheet("font-size: 15px; font-weight: 600;")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.reasons = note("")
        layout.addWidget(self.reasons)

        frow = QHBoxLayout()
        self.show_combo = QComboBox()
        self.show_combo.addItems(SHOW)
        frow.addWidget(QLabel("Show:"))
        frow.addWidget(self.show_combo)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter by folder or file name…")
        self.filter.setClearButtonEnabled(True)
        frow.addWidget(self.filter, 1)
        layout.addLayout(frow)

        self.model = MovesModel()
        self.proxy = MovesFilter()
        self.proxy.setSourceModel(self.model)
        self.view = QTableView()
        self.view.setModel(self.proxy)
        self.view.setSortingEnabled(True)
        self.view.sortByColumn(3, Qt.DescendingOrder)
        self.view.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.view.setSelectionMode(QAbstractItemView.SingleSelection)
        self.view.setTextElideMode(Qt.ElideMiddle)
        self.view.verticalHeader().setVisible(False)
        vh = self.view.horizontalHeader()
        vh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        vh.setSectionResizeMode(1, QHeaderView.Stretch)
        vh.setSectionResizeMode(2, QHeaderView.Stretch)
        vh.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        layout.addWidget(self.view, 1)

        buttons = QHBoxLayout()
        self.open_button = QPushButton("Show in File Explorer")
        self.open_button.setEnabled(False)
        self.export_button = QPushButton("Save the plan as CSV…")
        self.export_button.setEnabled(False)
        buttons.addWidget(self.open_button)
        buttons.addWidget(self.export_button)
        buttons.addStretch()
        self.next_button = QPushButton("Move to quarantine  →")
        self.next_button.setObjectName("primary")
        self.next_button.setEnabled(False)
        self.next_button.setToolTip("The Quarantine screen comes next.")
        buttons.addWidget(self.next_button)
        layout.addLayout(buttons)

        self.qtable.itemSelectionChanged.connect(
            lambda: self.change_button.setEnabled(bool(self.qtable.selectedItems()) and self.thread is None))
        self.qtable.itemDoubleClicked.connect(lambda *_: self.change_folder())
        self.change_button.clicked.connect(self.change_folder)
        self.run_button.clicked.connect(self.start)
        self.show_combo.currentIndexChanged.connect(lambda i: self.proxy.set(show=i))
        self.filter.textChanged.connect(lambda t: self.proxy.set(text=t))
        self.view.selectionModel().selectionChanged.connect(
            lambda *_: self.open_button.setEnabled(self._selected_move() is not None))
        self.open_button.clicked.connect(lambda: show_in_explorer(self._selected_move().original))
        self.export_button.clicked.connect(lambda: self.export_csv())
        self.next_button.clicked.connect(self.next_requested)

    # ------------------------------------------------------------ loading
    def load(self, scan_id):
        """Rebuild the plan from the saved keeper choices. Always re-read: they may have changed."""
        if scan_id is None or self.thread is not None:
            return
        with Store(self.db_path) as st:
            groups = st.load_groups(scan_id)
            saved, picks = st.load_choices(scan_id)
            last = st.latest_dry_run(scan_id)
            updated = st.choices_updated(scan_id)
        rules = keepers.Rules.from_dict(saved) if saved else keepers.Rules()
        self.scan_id = scan_id
        self.plans = keepers.plan(groups, rules, picks)
        vols = dryrun.volumes(self.plans)
        earlier = last[2].quarantines if last else {}
        self.quarantines = {v: earlier.get(v) or dryrun.default_quarantine(v) for v in vols}
        self._fill_quarantines(vols)
        self.run_button.setEnabled(bool(vols))
        # an earlier dry run is still valid only if the choices have not changed since
        if last and (updated is None or last[1] >= updated) and last[2].quarantines == self.quarantines:
            self._show(last[2], f"Dry run from {last[1]}. Run it again if files have changed since.")
        else:
            self._show(None, "Nothing to move with the current choices." if not vols else
                       "Check the quarantine folders, then run the dry run.")

    def _fill_quarantines(self, vols):
        self.qtable.setRowCount(len(vols))
        for row, (v, n) in enumerate(vols.items()):
            self.qtable.setItem(row, 0, QTableWidgetItem(v))
            self.qtable.setItem(row, 1, QTableWidgetItem(self.quarantines[v]))
            count = QTableWidgetItem(f"{n:,}")
            count.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.qtable.setItem(row, 2, count)

    def set_quarantine(self, vol, folder):
        """Use folder as the quarantine for drive vol. It must be on that drive."""
        folder = os.path.normpath(os.path.abspath(folder))
        if vol not in self.quarantines or dryrun.volume(folder) != vol:
            return False
        self.quarantines[vol] = folder
        self._fill_quarantines(dryrun.volumes(self.plans))
        self._show(None, "Quarantine folder changed. Run the dry run again.")
        return True

    def change_folder(self):
        items = self.qtable.selectedItems()
        if not items or self.thread is not None:
            return
        vol = self.qtable.item(items[0].row(), 0).text()
        folder = QFileDialog.getExistingDirectory(self, f"Quarantine folder on {vol}", vol)
        if folder and not self.set_quarantine(vol, folder):
            QMessageBox.warning(self, "Different drive",
                                f"The quarantine folder for {vol} must be on {vol}, so that moving "
                                "is instant and no data is copied.")

    # ------------------------------------------------------------ running
    def start(self):
        if self.thread is not None or not self.plans:
            return
        self._show(None, "")
        self.worker = DryRunWorker(self.scan_id, self.plans, dict(self.quarantines), self.db_path)
        self.thread = QThread(self)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_finished)
        self.worker.failed.connect(self._on_failed)
        for sig in (self.worker.finished, self.worker.failed):
            sig.connect(self.thread.quit)
        self.thread.finished.connect(self._cleanup)
        self.bar.setRange(0, 0)
        self.bar.setVisible(True)
        self.stage.setText("Checking every planned move…")
        self.run_button.setEnabled(False)
        self.change_button.setEnabled(False)
        self.thread.start()

    def _on_progress(self, done, total):
        self.bar.setRange(0, max(total, 1))
        self.bar.setValue(done)
        self.stage.setText(f"Checking every planned move: {done:,} of {total:,}")

    def _on_finished(self, dry, run_id):
        self._show(dry, "Dry run complete. Nothing was moved.")

    def _on_failed(self, message):
        self._show(None, "The dry run could not finish.")
        QMessageBox.critical(self, "Dry run failed", message)

    def _cleanup(self):
        self.thread.deleteLater()
        self.worker.deleteLater()
        self.thread = None
        self.worker = None
        self.bar.setVisible(False)
        self.run_button.setEnabled(bool(self.plans))
        self.change_button.setEnabled(bool(self.qtable.selectedItems()))

    # ------------------------------------------------------------ results
    def _show(self, dry, message):
        self.dry = dry
        self.stage.setText(message)
        self.model.set_moves(dry.moves if dry else [])
        self.export_button.setEnabled(dry is not None)
        self.next_button.setEnabled(False)          # until the Quarantine screen exists
        if dry is None:
            self.summary.setText("")
            self.reasons.setText("")
            return
        moving = len(dry.moving)
        self.summary.setText(f"{moving:,} copies would move to quarantine, freeing {fmt(dry.freed)}."
                             + (f" {len(dry.skipped):,} skipped." if dry.skipped else ""))
        self.reasons.setText("  ·  ".join(f"{n:,} {reason.replace('skipped: ', '')}"
                                          for reason, n in dry.reasons().items()))

    def _selected_move(self):
        rows = self.view.selectionModel().selectedRows()
        if not rows:
            return None
        return self.model.moves[self.proxy.mapToSource(rows[0]).row()]

    def export_csv(self, path=None):
        if not self.dry:
            return None
        if not path:
            path, _ = QFileDialog.getSaveFileName(self, "Save the plan", "dryrun.csv", "CSV files (*.csv)")
        if path:
            dryrun.write_log(self.dry, path)
        return path
