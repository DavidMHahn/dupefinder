"""A quick self-test of a built copy of the app: `dupefinder.exe --smoke-test`.

Without a screen, it opens the main window, scans a throwaway folder of known
duplicates, and checks the result. It never touches the person's data: the
folder and database are temporary. Returns 0 when everything works.
"""

import os
import tempfile


def run():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from .. import testdata
    from .window import MainWindow
    from .worker import ScanWorker

    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as tmp:
        data = testdata.make(os.path.join(tmp, "data"))
        db = os.path.join(tmp, "db", "smoke.db")
        got = {}
        worker = ScanWorker([data], db_path=db)
        worker.finished.connect(lambda res, scan_id: got.update(res=res))
        worker.failed.connect(lambda msg: got.update(error=msg))
        worker.run()
        window = MainWindow(db_path=db)
        ok = ("res" in got and len(got["res"].groups) == testdata.EXPECTED_GROUPS
              and got["res"].wasted == testdata.EXPECTED_WASTED and window.steps.count() == 8)
        window.close()
        app.processEvents()
    return 0 if ok else 1
