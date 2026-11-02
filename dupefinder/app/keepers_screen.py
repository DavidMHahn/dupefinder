"""Step 3: decide which copy of each group stays.

A few rules pick the keeper of every group; any group can be changed by hand.
Choices are saved with the scan. Nothing on this screen moves a file.
"""

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from .. import keepers
from ..common import fmt
from ..store import Store
from .review_screen import show_in_explorer
from .scan_screen import FolderList, heading, note
from .worker import default_db_path

MAX_SHOWN = 300          # groups listed at once; the filter finds the rest

DECISION_TEXT = {
    keepers.KEEP: "Keep",
    keepers.MOVE: "Move to quarantine",
    keepers.STAYS_FOLDER: "Stays (not in a folder to clean)",
    keepers.STAYS_NAME: "Stays (name never moves)",
}


class KeepersScreen(QWidget):
    next_requested = Signal()

    def __init__(self, db_path=None):
        super().__init__()
        self.db_path = db_path or default_db_path()
        self.scan_id = None
        self.groups = []
        self.rules = keepers.Rules()
        self.picks = {}              # group number -> path kept by hand
        self.plans = []
        self._loading = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)
        layout.addWidget(heading("Choose which copies to keep"))
        layout.addWidget(note("A few rules choose the copy to keep in every group. You can pick a "
                              "different copy for any group by double-clicking it. Nothing is moved "
                              "here: the next step previews every move first."))

        box = QGroupBox("Rules")
        box_layout = QVBoxLayout(box)
        form = QFormLayout()
        self.rule = QComboBox()
        for key, text in keepers.RULES.items():
            self.rule.addItem(text, key)
        form.addRow("Keep the copy with:", self.rule)
        self.skip = QLineEdit()
        self.skip.setToolTip("Comma-separated. * matches anything, e.g. AlbumArt*")
        form.addRow("Never move files named:", self.skip)
        box_layout.addLayout(form)
        lists = QHBoxLayout()
        self.prefer = FolderList(
            "Keep copies in these folders first",
            "Optional. If a group has a copy here, that copy is kept. The first folder listed wins.",
            "Add folder…", "Choose a folder whose copies you want to keep")
        self.only_from = FolderList(
            "Only remove copies from these folders",
            "Optional. When empty, extra copies may be moved from anywhere. When set, copies "
            "elsewhere are never moved.",
            "Add folder…", "Choose a folder to clean up")
        for fl in (self.prefer, self.only_from):
            fl.list.setMinimumHeight(56)
            fl.list.setMaximumHeight(90)
        lists.addWidget(self.prefer)
        lists.addSpacing(16)
        lists.addWidget(self.only_from)
        box_layout.addLayout(lists)
        layout.addWidget(box)

        self.summary = QLabel("")
        self.summary.setStyleSheet("font-weight: 600;")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        row = QHBoxLayout()
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter by folder or file name…")
        self.filter.setClearButtonEnabled(True)
        row.addWidget(self.filter, 1)
        self.shown_note = QLabel("")
        self.shown_note.setObjectName("note")
        row.addWidget(self.shown_note)
        layout.addLayout(row)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["Group and its copies", "Decision", "Size"])
        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.tree.setTextElideMode(Qt.ElideMiddle)
        layout.addWidget(self.tree, 1)

        buttons = QHBoxLayout()
        self.keep_button = QPushButton("Keep this copy")
        self.reset_button = QPushButton("Use the rules for this group")
        self.open_button = QPushButton("Show in File Explorer")
        for b in (self.keep_button, self.reset_button, self.open_button):
            b.setEnabled(False)
            buttons.addWidget(b)
        buttons.addStretch()
        self.next_button = QPushButton("Preview the moves (dry run)  →")
        self.next_button.setObjectName("primary")
        self.next_button.setEnabled(False)
        self.next_button.setToolTip("The Dry run screen comes next.")
        buttons.addWidget(self.next_button)
        layout.addLayout(buttons)

        self.rule.currentIndexChanged.connect(self._rules_changed)
        self.skip.editingFinished.connect(self._rules_changed)
        self.prefer.changed.connect(self._rules_changed)
        self.only_from.changed.connect(self._rules_changed)
        self.filter.textChanged.connect(self._fill_tree)
        self.tree.itemSelectionChanged.connect(self._update_buttons)
        self.tree.itemDoubleClicked.connect(lambda item, col: self.keep_selected())
        self.keep_button.clicked.connect(self.keep_selected)
        self.reset_button.clicked.connect(self.reset_selected)
        self.open_button.clicked.connect(lambda: show_in_explorer(self._selected()[1]))
        self.next_button.clicked.connect(self.next_requested)

    # ------------------------------------------------------------ loading and saving
    def load(self, scan_id):
        """Show a saved scan with its saved choices (or the default rules)."""
        if scan_id is None or scan_id == self.scan_id:
            return
        with Store(self.db_path) as st:
            self.groups = st.load_groups(scan_id)
            saved, self.picks = st.load_choices(scan_id)
        self.scan_id = scan_id
        self.rules = keepers.Rules.from_dict(saved) if saved else keepers.Rules()
        self._loading = True
        self.rule.setCurrentIndex(max(self.rule.findData(self.rules.keep), 0))
        self.skip.setText(", ".join(self.rules.skip_names))
        for fl, folders in ((self.prefer, self.rules.prefer), (self.only_from, self.rules.only_from)):
            fl.list.clear()
            for f in folders:
                fl.list.addItem(f)
        self._loading = False
        self._replan()

    def _rules_changed(self):
        if self._loading:
            return
        self.rules = keepers.Rules(
            keep=self.rule.currentData(),
            prefer=self.prefer.folders(),
            only_from=self.only_from.folders(),
            skip_names=[s.strip() for s in self.skip.text().split(",") if s.strip()],
        )
        self._save()
        self._replan()

    def _save(self):
        if self.scan_id is None:
            return
        with Store(self.db_path) as st:
            st.save_choices(self.scan_id, self.rules.to_dict(), self.picks)

    def _replan(self):
        self.plans = keepers.plan(self.groups, self.rules, self.picks)
        t = keepers.totals(self.plans)
        if not self.plans:
            self.summary.setText("No duplicates in this scan.")
        else:
            text = (f"{t.moves:,} extra copies would move to quarantine, freeing {fmt(t.freed)}. "
                    f"One copy stays in each of {t.groups:,} groups.")
            if t.by_hand:
                text += f" {t.by_hand:,} picked by hand."
            if t.stays:
                text += f" {t.stays:,} other copies stay because of a folder or name rule."
            self.summary.setText(text)
        self.next_button.setEnabled(False)      # until the Dry run screen exists
        self._fill_tree()

    # ------------------------------------------------------------ tree
    def _matches(self, gp, text):
        t = text.lower()
        return any(t in p.lower() for p in gp.status)

    def _fill_tree(self):
        text = self.filter.text().strip()
        selected = self._selected()
        plans = [gp for gp in self.plans if not text or self._matches(gp, text)]
        plans.sort(key=lambda gp: (-gp.size * (len(gp.status) - 1), gp.number))
        shown = plans[:MAX_SHOWN]
        self.tree.setUpdatesEnabled(False)
        self.tree.clear()
        bold = QFont()
        bold.setBold(True)
        for gp in shown:
            names = {os.path.basename(p) for p in gp.status}
            title = next(iter(names)) if len(names) == 1 else f"{len(names)} different names"
            how = "picked by hand" if gp.by_hand else "by the rules"
            top = QTreeWidgetItem([f"{title}  ·  {len(gp.status)} copies",
                                   f"frees {fmt(gp.freed)}, {how}", fmt(gp.size)])
            top.setData(0, Qt.UserRole, (gp.number, None))
            for p, decision in gp.status.items():
                child = QTreeWidgetItem([p, DECISION_TEXT[decision], ""])
                child.setData(0, Qt.UserRole, (gp.number, p))
                child.setToolTip(0, p)
                if decision == keepers.KEEP:
                    child.setFont(0, bold)
                    child.setFont(1, bold)
                top.addChild(child)
            self.tree.addTopLevelItem(top)
            top.setExpanded(True)
        self.tree.setUpdatesEnabled(True)
        if len(plans) > len(shown):
            self.shown_note.setText(f"Showing the {len(shown):,} biggest of {len(plans):,} groups. "
                                    "Use the filter to find others.")
        else:
            n = len(plans)
            self.shown_note.setText(f"{n:,} group{' matches' if n == 1 else 's match'}" if text else "")
        self._reselect(selected)
        self._update_buttons()

    def _reselect(self, selected):
        number, path = selected
        if number is None:
            return
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            if top.data(0, Qt.UserRole)[0] != number:
                continue
            target = top
            for j in range(top.childCount()):
                if top.child(j).data(0, Qt.UserRole)[1] == path:
                    target = top.child(j)
            self.tree.setCurrentItem(target)
            return

    def _selected(self):
        """(group number, path) of the selected row; path is None for a group row."""
        items = self.tree.selectedItems()
        return items[0].data(0, Qt.UserRole) if items else (None, None)

    def _plan(self, number):
        return self.plans[number - 1] if number else None

    def _update_buttons(self):
        number, path = self._selected()
        gp = self._plan(number)
        movable = (gp is not None and path is not None
                   and gp.status.get(path) in (keepers.MOVE, keepers.STAYS_FOLDER))
        self.keep_button.setEnabled(movable)
        self.reset_button.setEnabled(gp is not None and gp.by_hand)
        self.open_button.setEnabled(path is not None)

    # ------------------------------------------------------------ picking by hand
    def keep_selected(self):
        number, path = self._selected()
        gp = self._plan(number)
        if gp is None or path is None or gp.status.get(path) not in (keepers.MOVE, keepers.STAYS_FOLDER):
            return
        self.picks[number] = path
        self._save()
        self._replan()

    def reset_selected(self):
        number, _ = self._selected()
        if self.picks.pop(number, None) is not None:
            self._save()
            self._replan()
