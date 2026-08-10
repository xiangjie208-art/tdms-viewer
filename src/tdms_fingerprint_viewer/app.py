from __future__ import annotations

import sys

import pyqtgraph as pg
from PySide6.QtCore import QLocale, Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

from .main_window import APP_NAME, MainWindow


def configure_chinese_font(app):
    for path in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf"):
        font_id = QFontDatabase.addApplicationFont(path)
        if font_id >= 0:
            families = QFontDatabase.applicationFontFamilies(font_id)
            if families:
                app.setFont(QFont(families[0], 9)); return
    app.setFont(QFont("Microsoft YaHei UI", 9))


def main():
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME); app.setOrganizationName("TDMSViewerPortable"); app.setStyle("Fusion")
    configure_chinese_font(app)
    QLocale.setDefault(QLocale(QLocale.Chinese, QLocale.China))
    pg.setConfigOptions(antialias=False, foreground="#F4F7FA", background="#05070A")
    window = MainWindow(); window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
