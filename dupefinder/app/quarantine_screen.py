"""Step 5: move the extra copies into quarantine. The first step that changes files.

It carries out the saved dry run and nothing else, checks each copy again just
before moving it, logs every move as it happens, and can put everything back.
Nothing is ever deleted here.
"""

import os

from PySide6.QtCore import Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QFrame, QHBoxLayout, QLabel, QMessageBox, QProgressBar, QPushButton, QVBoxLayout,
    QWidget,
)

from ..common import fmt
from ..store import Store
from .scan_screen import heading, note
from .worker import QuarantineWorker, UndoWorker, default_db_path


class QuarantineScreen(QWidget):
    next_requested = Signal()
    changed = Signal()               # files were moved or put back

    def __init__(self, db_path=None):
        super().__init__()
        self.db_path = db_path or default_db_path()
        self.scan_id = None
        self.dry_run_id = None
        self.dry = None
        self.last_run = None         # newest quarantine run of this scan (dict), or None
        self.thread = None
        self.worker = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        layout.addWidget(heading("Move extra copies to quarantine"))
        layout.addWidget(note(
            "This carries out your dry run. Each extra copy is moved, not deleted, into the quarantine "
            "folder on its drive, keeping its folder path. Every copy is checked again just before it "
            "moves, every move is logged, and Put everything back undoes it."))

        self.ready = QLabel("")
        self.ready.setWordWrap(True)
        self.ready.setStyleSheet("font-size: 15px; font-weight: 600;")
        layout.addWidget(self.ready)
        self.where = note("")
        layout.addWidget(self.where)

        self.verify = QCheckBox("Check each copy is still identical to the kept copy before moving it "
                                "(reads both files again: slower, safest)")
        self.verify.setChecked(True)
        layout.addWidget(self.verify)

        row = QHBoxLayout()
        self.start_button = QPushButton("Move to quarantine")
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

        self.results = QFrame()
        self.results.setFrameShape(QFrame.StyledPanel)
        rl = QVBoxLayout(self.results)
        rl.setContentsMargins(16, 12, 16, 12)
        self.result_title = heading("", 15)
        self.result_text = note("")
        self.log_label = note("")
        self.log_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        rl.addWidget(self.result_title)
        rl.addWidget(self.result_text)
        rl.addWidget(self.log_label)
        rb = QHBoxLayout()
        self.open_log_button = QPushButton("Open the log folder")
        self.undo_button = QPushButton("Put everything back")
        rb.addWidget(self.open_log_button)
        rb.addWidget(self.undo_button)
        rb.addStretch()
        rl.addLayout(rb)
        self.results.setVisible(False)
        layout.addWidget(self.results)
        layout.addStretch()

        buttons = QHBoxLayout()
        buttons.addStretch()
        self.next_button = QPushButton("Verify the quarantine  →")
        self.next_button.setObjectName("primary")
        self.next_button.setEnabled(False)
        buttons.addWidget(self.next_button)
        layout.addLayout(buttons)

        self.start_button.clicked.connect(self.start)
        self.stop_button.clicked.connect(self.stop)
        self.undo_button.clicked.connect(self.undo)
        self.open_log_button.clicked.connect(
            lambda: self.last_run and QDesktopServices.openUrl(
                QUrl.fromLocalFile(os.path.dirname(self.last_run["log_path"]))))
        self.next_button.clicked.connect(self.next_requested)

    # ------------------------------------------------------------ dialogs (replaced in tests)
    def confirm(self, title, text):
        return QMessageBox.question(self, title, text) == QMessageBox.Yes

    def error(self, title, text):
        QMessageBox.critical(self, title, text)

    # ------------------------------------------------------------ loading
    def load(self, scan_id):
        if scan_id is None or self.thread is not None:
            return
        with Store(self.db_path) as st:
            current = st.current_dry_run(scan_id)
            runs = st.quarantine_runs(scan_id)
        self.scan_id = scan_id
        self.dry_run_id, _, self.dry = current if current else (None, None, None)
        created = current[1] if current else None
        self.last_run = runs[0] if runs else None
        self._refresh(created)

    def _refresh(self, created=None):
        """Work out what can be done now and say so."""
        run = self.last_run
        done_already = (run is not None and run["dry_run_id"] == self.dry_run_id
                        and not run["undone"])
        moving = self.dry.moving if self.dry else []
        if self.dry is None:
            self.ready.setText("Run the dry run first (step 4). It needs to be run again whenever "
                               "the keeper choices change.")
        elif done_already:
            self.ready.setText("This dry run has been carried out. To move more, choose keepers "
                               "and run a new dry run.")
        elif not moving:
            self.ready.setText("The dry run found nothing that can be moved.")
        else:
            self.ready.setText(f"Ready to move {len(moving):,} copies to quarantine, freeing "
                               f"{fmt(self.dry.freed)}" + (f" (dry run from {created})." if created else "."))
        if self.dry and moving and not done_already:
            self.where.setText("Quarantine folders:\n" + "\n".join(
                f"  {v}  →  {q}" for v, q in sorted(self.dry.quarantines.items())))
        else:
            self.where.setText("")
        can_start = bool(self.dry and moving and not done_already)
        self.start_button.setEnabled(can_start and self.thread is None)
        self.start_button.setText(f"Move {len(moving):,} copies to quarantine" if can_start
                                  else "Move to quarantine")
        self._show_run()

    def _show_run(self):
        run = self.last_run
        if run is None:
            self.results.setVisible(False)
            self.next_button.setEnabled(False)
            return
        self.results.setVisible(True)
        if run["undone"]:
            self.result_title.setText("Everything was put back")
            self.result_text.setText(f"The move of {run['started']} was undone on {run['undone']}.")
            self.undo_button.setEnabled(False)
        elif run["finished"] is None:
            self.result_title.setText("The last move did not finish")
            self.result_text.setText("The app was closed while moving. The log lists every copy that "
                                     "was moved, and Put everything back works from it.")
            self.undo_button.setEnabled(self.thread is None)
        else:
            stopped = " You stopped it part-way." if run["stopped"] else ""
            skipped = (f" {run['skipped']:,} skipped because they changed since the dry run."
                       if run["skipped"] else "")
            self.result_title.setText(f"Moved {run['moved']:,} copies to quarantine, freeing "
                                      f"{fmt(run['freed'] or 0)}")
            self.result_text.setText(f"Nothing was deleted.{stopped}{skipped} Keep the quarantine "
                                     "until you are sure nothing is missing; the next step checks it.")
            self.undo_button.setEnabled(self.thread is None and bool(run["moved"]))
        self.log_label.setText(f"Moves log: {run['log_path']}")
        self.next_button.setEnabled(not run["undone"] and bool(run["moved"]))

    # ------------------------------------------------------------ moving
    def start(self):
        if self.thread is not None or not self.dry or not self.start_button.isEnabled():
            return
        n = len(self.dry.moving)
        if not self.confirm("Move to quarantine",
                            f"Move {n:,} copies ({fmt(self.dry.freed)}) to quarantine?\n\n"
                            "Nothing is deleted, and Put everything back undoes it."):
            return
        self.worker = QuarantineWorker(self.scan_id, self.dry_run_id, self.dry,
                                       self.verify.isChecked(), self.db_path)
        self.worker.progress.connect(self._on_progress)
        # bound methods, not lambdas, so Qt runs them on the window's thread
        self.worker.finished.connect(self._on_moved)
        self.worker.failed.connect(self._on_move_failed)
        self._run_thread([self.worker.finished, self.worker.failed])
        self.stage.setText("Moving copies to quarantine…")
        self.stop_button.setEnabled(True)

    def stop(self):
        if isinstance(self.worker, QuarantineWorker):
            self.worker.stop()
            self.stop_button.setEnabled(False)
            self.stage.setText("Stopping after the current file…")

    def undo(self):
        run = self.last_run
        if self.thread is not None or run is None or run["undone"]:
            return
        if not self.confirm("Put everything back",
                            "Move every copy in this moves log back to where it was?"):
            return
        self.worker = UndoWorker(run["id"], run["log_path"], self.db_path)
        self.worker.finished.connect(self._on_undone)
        self.worker.failed.connect(self._on_undo_failed)
        self._run_thread([self.worker.finished, self.worker.failed])
        self.stage.setText("Putting copies back…")

    def _run_thread(self, ends):
        self.thread = QThread(self)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        for sig in ends:
            sig.connect(self.thread.quit)
        self.thread.finished.connect(self._cleanup)
        self.bar.setRange(0, 0)
        self.bar.setVisible(True)
        self.start_button.setEnabled(False)
        self.undo_button.setEnabled(False)
        self.verify.setEnabled(False)
        self.thread.start()

    def _on_progress(self, done, total):
        self.bar.setRange(0, max(total, 1))
        self.bar.setValue(done)
        self.stage.setText(f"Moving copies to quarantine: {done:,} of {total:,}")

    def _on_moved(self, res):
        self.stage.setText("Done. Nothing was deleted.")
        self.changed.emit()

    def _on_move_failed(self, message):
        self._on_failed("Moving stopped with an error", message)

    def _on_undo_failed(self, message):
        self._on_failed("Putting back stopped with an error", message)

    def _on_undone(self, back, total, problems):
        if problems:
            self.stage.setText(f"Put back {back:,} of {total:,} copies. {len(problems):,} could not be "
                               "put back; see the details.")
            self.error("Some copies were not put back",
                       "\n".join(problems[:20]) + ("\n…" if len(problems) > 20 else ""))
        else:
            self.stage.setText(f"Put back {back:,} copies. Everything is where it was.")
        self.changed.emit()

    def _on_failed(self, title, message):
        self.stage.setText(title + ". The moves log lists everything that was moved.")
        self.error(title, message)

    def _cleanup(self):
        self.thread.deleteLater()
        self.worker.deleteLater()
        self.thread = None
        self.worker = None
        self.bar.setVisible(False)
        self.stop_button.setEnabled(False)
        self.verify.setEnabled(True)
        stage = self.stage.text()
        sid, self.scan_id = self.scan_id, None
        self.load(sid)                   # re-read what happened from the database
        self.stage.setText(stage)
