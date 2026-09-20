"""Dialog for creating a machine-learning dataset from saved regions."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from threading import Event

from PySide6.QtCore import QObject, QRunnable, QSignalBlocker, QThreadPool, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .dataset_export import DatasetSource, build_ml_dataset, discover_dataset_sources
from .widgets import WheelSafeDoubleSpinBox


class DatasetBuildSignals(QObject):
    progress = Signal(int, int, str)
    finished = Signal(object)
    failed = Signal(str)


class DatasetBuildWorker(QRunnable):
    def __init__(self, root, output_parent, selected_sources, threshold_pa, builder=build_ml_dataset):
        super().__init__()
        self.root = Path(root)
        self.output_parent = Path(output_parent)
        self.selected_sources = tuple(selected_sources)
        self.threshold_pa = float(threshold_pa)
        self.builder = builder
        self.cancelled = Event()
        self.signals = DatasetBuildSignals()

    def cancel(self):
        self.cancelled.set()

    @Slot()
    def run(self):
        try:
            summary = self.builder(
                self.root,
                self.output_parent,
                self.selected_sources,
                self.threshold_pa,
                progress=self.signals.progress.emit,
                cancelled=self.cancelled.is_set,
            )
        except Exception as exc:
            self.signals.failed.emit(str(exc))
            return
        self.signals.finished.emit(summary)


class DatasetDialog(QDialog):
    def __init__(self, parent=None, *, discoverer=discover_dataset_sources, builder=build_ml_dataset):
        super().__init__(parent)
        self.discoverer = discoverer
        self.builder = builder
        self.sources: list[DatasetSource] = []
        self.root: Path | None = None
        self.output_parent: Path | None = None
        self.worker = None
        self.setWindowTitle("制作机器学习数据集")
        self.resize(900, 620)
        self._build_ui()
        self.refresh_build_enabled()

    def _path_row(self, button_text, callback):
        widget = QWidget(self)
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        line = QLineEdit(widget)
        line.setReadOnly(True)
        button = QPushButton(button_text, widget)
        button.clicked.connect(callback)
        layout.addWidget(line, 1)
        layout.addWidget(button)
        return widget, line, button

    def _build_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()
        root_row, self.root_edit, self.root_button = self._path_row("选择…", self.choose_root)
        output_row, self.output_edit, self.output_button = self._path_row("选择…", self.choose_output_parent)
        form.addRow("分子总目录", root_row)
        form.addRow("导出位置", output_row)
        layout.addLayout(form)

        help_label = QLabel("每个一级子文件夹对应一个分子来源；可以编辑标签，将多个文件夹合并为同一类别。")
        help_label.setWordWrap(True)
        layout.addWidget(help_label)

        self.source_table = QTableWidget(0, 5, self)
        self.source_table.setHorizontalHeaderLabels(
            ["使用", "分子文件夹", "数据集标签", "TDMS 数量", "已保存片段数量"]
        )
        self.source_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.source_table.verticalHeader().setVisible(False)
        header = self.source_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.source_table.itemChanged.connect(self.refresh_build_enabled)
        layout.addWidget(self.source_table, 1)

        parameter_form = QFormLayout()
        self.threshold_spin = WheelSafeDoubleSpinBox(self)
        self.threshold_spin.setRange(0.0, 1_000_000.0)
        self.threshold_spin.setDecimals(3)
        self.threshold_spin.setSingleStep(1.0)
        self.threshold_spin.setValue(10.0)
        self.threshold_spin.setSuffix(" pA")
        self.threshold_spin.setKeyboardTracking(False)
        parameter_form.addRow("特征峰幅值阈值（pA）", self.threshold_spin)
        layout.addLayout(parameter_form)

        self.status_label = QLabel("请选择包含各分子文件夹的总目录。", self)
        self.status_label.setWordWrap(True)
        self.status_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.status_label)
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.stop_button = QPushButton("停止", self)
        self.stop_button.setEnabled(False)
        self.build_button = QPushButton("制作数据集", self)
        self.close_button = QPushButton("关闭", self)
        self.stop_button.clicked.connect(self.stop_build)
        self.build_button.clicked.connect(self.start_build)
        self.close_button.clicked.connect(self.reject)
        buttons.addWidget(self.stop_button)
        buttons.addWidget(self.build_button)
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)

    def choose_root(self):
        folder = QFileDialog.getExistingDirectory(self, "选择分子总目录", str(self.root or Path.home()))
        if folder:
            self.set_root(Path(folder))

    def choose_output_parent(self):
        folder = QFileDialog.getExistingDirectory(self, "选择数据集导出位置", str(self.output_parent or Path.home()))
        if folder:
            self.set_output_parent(Path(folder))

    def set_root(self, root: Path):
        self.root = Path(root).resolve()
        self.root_edit.setText(str(self.root))
        try:
            self.sources = self.discoverer(self.root)
        except Exception as exc:
            self.sources = []
            self.status_label.setText(f"无法读取总目录：{exc}")
            self._populate_sources(update_status=False)
        else:
            self._populate_sources()
        self.refresh_build_enabled()

    def set_output_parent(self, output_parent: Path):
        self.output_parent = Path(output_parent).resolve()
        self.output_edit.setText(str(self.output_parent))
        self.refresh_build_enabled()

    def _populate_sources(self, update_status=True):
        blocker = QSignalBlocker(self.source_table)
        self.source_table.setRowCount(len(self.sources))
        for row, source in enumerate(self.sources):
            use_item = QTableWidgetItem()
            use_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable)
            use_item.setCheckState(Qt.Checked if source.included else Qt.Unchecked)
            use_item.setData(Qt.UserRole, source)
            folder_item = QTableWidgetItem(source.folder_name)
            folder_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            label_item = QTableWidgetItem(source.label)
            label_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable)
            tdms_item = QTableWidgetItem(str(source.tdms_count))
            tdms_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            region_item = QTableWidgetItem(str(source.region_count))
            region_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            for item in (tdms_item, region_item):
                item.setTextAlignment(Qt.AlignCenter)
            for column, item in enumerate((use_item, folder_item, label_item, tdms_item, region_item)):
                self.source_table.setItem(row, column, item)
        del blocker
        if update_status:
            total = sum(source.region_count for source in self.sources)
            self.status_label.setText(f"已发现 {len(self.sources)} 个分子文件夹，共 {total} 条已保存片段。")

    def selected_sources(self) -> list[DatasetSource]:
        selected = []
        for row in range(self.source_table.rowCount()):
            use_item = self.source_table.item(row, 0)
            label_item = self.source_table.item(row, 2)
            if use_item is None or use_item.checkState() != Qt.Checked:
                continue
            source = use_item.data(Qt.UserRole)
            if isinstance(source, DatasetSource):
                selected.append(replace(source, label=label_item.text().strip(), included=True))
        return selected

    def refresh_build_enabled(self, *_):
        selected = self.selected_sources()
        valid = (
            self.root is not None
            and self.output_parent is not None
            and any(source.region_count > 0 for source in selected)
            and all(source.label for source in selected)
        )
        self.build_button.setEnabled(bool(valid) and self.worker is None)

    def set_running(self, running: bool):
        for widget in (self.root_button, self.output_button, self.source_table, self.threshold_spin):
            widget.setEnabled(not running)
        self.build_button.setEnabled(False if running else self.build_button.isEnabled())
        self.stop_button.setEnabled(running)
        self.close_button.setEnabled(not running)
        if not running:
            self.refresh_build_enabled()

    def start_build(self):
        selected = self.selected_sources()
        if self.root is None or self.output_parent is None or not self.build_button.isEnabled():
            return
        self.progress_bar.setRange(0, max(1, sum(source.region_count for source in selected)))
        self.progress_bar.setValue(0)
        self.status_label.setText("正在准备数据集…")
        self.worker = DatasetBuildWorker(
            self.root,
            self.output_parent,
            selected,
            self.threshold_spin.value(),
            self.builder,
        )
        self.worker.signals.progress.connect(self.on_progress)
        self.worker.signals.finished.connect(self.on_finished)
        self.worker.signals.failed.connect(self.on_failed)
        self.set_running(True)
        QThreadPool.globalInstance().start(self.worker)

    def stop_build(self):
        if self.worker is None:
            return
        self.worker.cancel()
        self.stop_button.setEnabled(False)
        self.status_label.setText("正在停止，等待当前操作完成…")

    @Slot(int, int, str)
    def on_progress(self, done: int, total: int, description: str):
        self.progress_bar.setRange(0, max(1, total))
        self.progress_bar.setValue(done)
        self.status_label.setText(f"正在处理 {done}/{total}：{description}")

    @Slot(object)
    def on_finished(self, summary):
        self.worker = None
        self.set_running(False)
        if summary.cancelled:
            self.status_label.setText("已停止，本次未创建数据集。")
            return
        self.progress_bar.setValue(self.progress_bar.maximum())
        self.status_label.setText(
            f"数据集制作完成：{summary.sample_count} 个有效样本，跳过 {len(summary.skipped)} 个。\n"
            f"{summary.output_dir}"
        )
        message = QMessageBox(self)
        message.setWindowTitle("数据集制作完成")
        message.setIcon(QMessageBox.Information)
        message.setText(f"已生成 {summary.sample_count} 个有效样本。")
        message.setInformativeText(f"输出目录：\n{summary.output_dir}\n\n跳过样本：{len(summary.skipped)}")
        if summary.skipped:
            message.setDetailedText("\n".join(f"{item.source}：{item.reason}" for item in summary.skipped))
        message.exec()

    @Slot(str)
    def on_failed(self, error: str):
        self.worker = None
        self.set_running(False)
        self.status_label.setText(f"数据集制作失败：{error}")
        QMessageBox.critical(self, "无法制作数据集", error)
