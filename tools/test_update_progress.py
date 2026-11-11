"""Update progress integration tests, with no real downloads or installation."""

import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from core.update import UpdateInfo
from ui import window


class FakeDownloader(QObject):
    progress = Signal("qlonglong", "qlonglong")
    stage_changed = Signal(str)
    finished = Signal(str, str)

    def start(self, info):
        return True


class ProgressTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        with patch.object(window, "Sfx"), patch.object(window.QTimer, "singleShot"):
            self.pet = window.PetWindow()
        self.pet.sfx.volume = 0.35
        self.pet.sfx.enabled = True
        self.info = UpdateInfo(version="99.0.0", asset_url="https://example.test/update.zip",
                               asset_size=100)
        self.pet._update_info = self.info
        self.factory = patch.object(window.updater_net, "UpdateDownloader", FakeDownloader)
        self.factory.start()

    def tearDown(self):
        self.factory.stop()
        self.pet.timer.stop()
        self.pet.overlay.close()
        if self.pet._update_progress:
            self.pet._update_progress.close()
        self.pet.close()
        self.pet.deleteLater()

    def test_progress_and_reopen_without_duplicate_download(self):
        self.pet._start_download(self.info)
        worker = self.pet._downloader
        panel = self.pet._update_progress
        worker.progress.emit(2**33, 2**34)
        self.assertEqual(panel.bar.value(), 50)
        self.assertIn("8192.0 MB", panel.detail.text())
        worker.progress.emit(10, 0)
        self.assertEqual(panel.bar.maximum(), 0)
        self.assertIn("总大小未知", panel.detail.text())
        panel.close()
        self.pet._act_update()
        self.assertTrue(panel.isVisible())
        self.assertIs(self.pet._downloader, worker)
        self.pet._start_download(self.info)
        self.assertIs(self.pet._downloader, worker)
        menu = self.pet._build_menu()
        self.assertIn("查看更新进度", [action.text() for action in menu.actions()])
        worker.stage_changed.emit("下载完成，正在校验安装包……")
        self.assertIn("校验", panel.status.text())

    def test_failure_then_retry_and_success(self):
        self.pet._start_download(self.info)
        self.pet._downloader.finished.emit("网络连接中断", "")
        panel = self.pet._update_progress
        self.assertEqual(panel.status.text(), "更新失败")
        self.assertEqual(panel.detail.text(), "网络连接中断")
        self.assertTrue(panel.isVisible())
        self.assertIsNone(self.pet._downloader)
        self.pet._start_download(self.info)
        self.assertEqual(panel.button.text(), "收起")
        with patch.object(window.updater, "extract", return_value="fake-package"), \
                patch.object(self.pet, "_ask_restart", return_value=False) as ask, \
                patch.object(self.pet, "_apply_update") as apply:
            self.pet._downloader.finished.emit("", "fake.zip")
            ask.assert_called_once_with(self.info)
            apply.assert_not_called()
        self.assertFalse(panel.isVisible())
        self.assertFalse(self.pet._update_finishing)

    def test_extraction_error_is_visible(self):
        self.pet._start_download(self.info)
        with patch.object(window.updater, "extract", side_effect=OSError("disk full")):
            self.pet._downloader.finished.emit("", "fake.zip")
        self.assertIn("disk full", self.pet._update_progress.detail.text())
        self.assertTrue(self.pet._update_progress.isVisible())
        self.assertFalse(self.pet._update_finishing)

    def test_restart_after_success(self):
        self.pet._start_download(self.info)
        with patch.object(window.updater, "extract", return_value="fake-package"), \
                patch.object(self.pet, "_ask_restart", return_value=True), \
                patch.object(self.pet, "_apply_update") as apply:
            self.pet._downloader.finished.emit("", "fake.zip")
            apply.assert_called_once_with("fake-package")
        self.assertIsNone(self.pet._downloader)
        self.assertFalse(self.pet._update_finishing)


if __name__ == "__main__":
    unittest.main()
