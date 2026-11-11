"""Exercise update dialogs through the real entry point, without network or downloads.

Run: python tools/test_update_dialogs.py
"""

import os
from pathlib import Path
import subprocess
import sys

BASE = Path(__file__).resolve().parents[1]


def run_case(case):
    sys.path.insert(0, str(BASE))
    from types import SimpleNamespace
    import uuid

    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

    import main
    from core import diag
    from ui import window

    real_window = window.PetWindow
    accepted = case.endswith("yes")
    restart = case.startswith("restart")

    class TestWindow(QWidget):
        def __init__(self):
            super().__init__()
            self.setWindowFlags(Qt.WindowType.Tool)
            self.info = SimpleNamespace(display="v99.0.0", notes="test")
            QTimer.singleShot(0, self.exercise)

        def exercise(self):
            QTimer.singleShot(40, self.answer)
            dialog = real_window._ask_restart if restart else real_window._ask_update
            result = dialog(self, self.info)
            if result != accepted:
                print("FAIL: wrong dialog result", flush=True)
                QApplication.instance().quit()
                return
            # The old setting quits the outer loop before this callback can run.
            QTimer.singleShot(150, self.verify_alive)

        def answer(self):
            box = QApplication.activeModalWidget()
            if not isinstance(box, QMessageBox):
                return
            role = (QMessageBox.ButtonRole.AcceptRole if accepted
                    else QMessageBox.ButtonRole.RejectRole)
            for button in box.buttons():
                if box.buttonRole(button) == role:
                    button.click()
                    return

        def verify_alive(self):
            if self.isVisible():
                print("PASS: " + case, flush=True)
            # Explicit exit must still stop the application with auto-quit disabled.
            real_window._quit_hard(self)

    diag.setup = lambda *_: None
    diag.log = lambda *_: None
    main.SINGLETON = "naiwa-dialog-test-" + uuid.uuid4().hex
    window.PetWindow = TestWindow
    main.main()


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--case":
        run_case(sys.argv[2])
        return
    for case in ("update-yes", "update-no", "restart-yes", "restart-no"):
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
        result = subprocess.run(
            [sys.executable, __file__, "--case", case], cwd=BASE,
            env=env, capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0 or "PASS: " + case not in result.stdout:
            raise SystemExit("FAIL: %s\n%s\n%s" %
                             (case, result.stdout, result.stderr))
        print(result.stdout.strip())


if __name__ == "__main__":
    main()
