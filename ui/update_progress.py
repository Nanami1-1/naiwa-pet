"""更新下载进度窗口；关闭窗口只收起显示，不中断下载。"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QLabel, QProgressBar, QPushButton, QVBoxLayout

import config as C


def _size(value):
    return "%.1f MB" % (value / 1024 / 1024)


class UpdateProgress(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("奶蛙更新")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setMinimumWidth(360)
        self.setStyleSheet('''
            QDialog { background: #fffbf3; }
            QLabel { color: #3a3024; font-family: "%s"; font-size: 13px; }
            QProgressBar { border: 1px solid #e8dac4; border-radius: 6px;
                           background: #eee5d4; height: 22px; text-align: center; }
            QProgressBar::chunk { background: #f0a830; border-radius: 5px; }
            QPushButton { padding: 6px 16px; }
        ''' % C.FONT)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(12)
        self.heading = QLabel()
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.bar = QProgressBar()
        self.detail = QLabel()
        self.button = QPushButton("收起")
        self.button.clicked.connect(self.hide)
        for widget in (self.heading, self.status, self.bar, self.detail, self.button):
            layout.addWidget(widget)

    def begin(self, version, total=0):
        self.heading.setText("正在更新到 %s" % version)
        self.status.setText("正在连接下载服务器……")
        self.detail.setText("收起窗口后会继续下载，可从右键菜单重新查看。")
        self.button.setText("收起")
        self.bar.setRange(0, 100 if total > 0 else 0)
        self.bar.setValue(0)

    def show_progress(self):
        self.show()
        self.raise_()
        self.activateWindow()

    def set_progress(self, got, total):
        self.status.setText("正在下载安装包……")
        if total > 0:
            self.bar.setRange(0, 100)
            self.bar.setValue(max(0, min(100, int(got * 100 / total))))
            self.detail.setText("%s / %s" % (_size(got), _size(total)))
        else:
            self.bar.setRange(0, 0)
            self.detail.setText("已下载 %s（总大小未知）" % _size(got))

    def set_stage(self, text):
        self.status.setText(text)
        self.bar.setRange(0, 0)

    def fail(self, error):
        self.status.setText("更新失败")
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.detail.setText(error)
        self.detail.setWordWrap(True)
        self.detail.setTextFormat(Qt.TextFormat.PlainText)
        self.button.setText("关闭")
        self.show_progress()
