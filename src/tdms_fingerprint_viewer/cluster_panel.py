"""Manual review of transient Gaussian cluster candidates."""
from threading import Event
import pyqtgraph as pg
from PySide6.QtCore import QObject, QRunnable, Signal, Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QFormLayout, QHBoxLayout, QLabel, QComboBox,
    QDoubleSpinBox, QPushButton, QTableWidget, QTableWidgetItem, QAbstractItemView, QHeaderView, QProgressBar,
)
from .clustering import find_clusters
from .core import minmax_envelope, load_trace


CURRENT_TO_PA = {"A": 1e12, "mA": 1e9, "uA": 1e6, "µA": 1e6, "μA": 1e6, "nA": 1e3, "pA": 1.0}
# User-confirmed instrument calibration, not a general voltage/current conversion.
VOLTAGE_TO_PA = 1000.0
VOLTAGE_UNITS = {"v", "volt", "volts"}


def current_factor(unit):
    return VOLTAGE_TO_PA if unit.strip().casefold() in VOLTAGE_UNITS else CURRENT_TO_PA.get(unit.strip())


def file_stamp(path):
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns


class BatchSignals(QObject):
    item = Signal(object)
    done = Signal(object)


class BatchClusterWorker(QRunnable):
    """Load one file at a time; retain candidates, never the batch's raw traces."""
    def __init__(self, files, channel_key, parameters):
        super().__init__()
        self.files, self.channel_key, self.parameters = files, channel_key, parameters
        self.cancelled = Event()
        self.signals = BatchSignals()

    def run(self):
        success = failed = 0
        for index, path in enumerate(self.files):
            if self.cancelled.is_set(): break
            payload = {"path": path, "index": index + 1}
            try:
                stamp = file_stamp(path)
                values, channel, _ = load_trace(path, self.channel_key)
                if channel.key != self.channel_key:
                    raise ValueError(f"缺少通道 {self.channel_key}")
                factor = current_factor(channel.unit)
                if factor is None:
                    raise ValueError(f"无法换算单位 {channel.unit} 为 pA")
                if self.cancelled.is_set(): break
                parameters = dict(self.parameters, unit=channel.unit, native_to_pa_factor=factor, scope=0)
                parameters["baseline"] /= factor
                parameters["amplitude"] /= factor
                result = find_clusters(values, channel.dt, parameters)
                if file_stamp(path) != stamp:
                    raise ValueError("分析期间文件发生变化，请重新运行")
                payload.update(result=result, stamp=stamp, channel=channel.key)
                success += 1
            except Exception as exc:
                payload["error"] = str(exc); failed += 1
            if self.cancelled.is_set(): break
            self.signals.item.emit(payload)
        self.signals.done.emit({"success": success, "failed": failed, "cancelled": self.cancelled.is_set()})


class Signals(QObject):
    done = Signal(object)
    failed = Signal(object)


class ClusterWorker(QRunnable):
    def __init__(self, token, values, dt, parameters, offset):
        super().__init__()
        self.signals = Signals()
        self.args = values, dt, parameters, offset
        self.token = token

    def run(self):
        try:
            result = find_clusters(*self.args)
            self.signals.done.emit((self.token, result))
        except Exception as exc:
            self.signals.failed.emit((self.token, str(exc)))


class ClusterPanel(QWidget):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.token = 0
        self.result = None
        self.workers = set()
        self.overlays = []
        self.unit = None
        self.to_pa = None
        self.loading = False
        self.batch_worker = None
        self.batch_cache = {}
        self.restoring_parameters = False
        layout = QVBoxLayout(self)
        file_row = QHBoxLayout(); layout.addLayout(file_row)
        self.previous_file_button = QPushButton("上一文件")
        self.file_combo = QComboBox()
        self.file_combo.setMinimumWidth(0)
        self.file_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.file_combo.setMinimumContentsLength(12)
        self.file_combo.setPlaceholderText("请先打开数据文件夹")
        self.file_combo.setAccessibleName("选择 TDMS 文件")
        self.next_file_button = QPushButton("下一文件")
        self.file_position_label = QLabel("0 / 0")
        file_row.addWidget(self.previous_file_button)
        file_row.addWidget(self.file_combo, 1)
        file_row.addWidget(self.next_file_button)
        file_row.addWidget(self.file_position_label)
        self.previous_file_button.clicked.connect(window.previous_file)
        self.next_file_button.clicked.connect(window.next_file)
        self.file_combo.activated.connect(window.file_list.setCurrentRow)
        window.file_list.currentRowChanged.connect(self.sync_file_selection)
        self.refresh_files()
        form = QFormLayout(); layout.addLayout(form)
        self.unit_label = QLabel("请先载入通道")
        form.addRow("幅值单位", self.unit_label)
        self.scope = QComboBox(); self.scope.addItems(["当前完整文件", "当前框选区间"])
        form.addRow("分析范围", self.scope)
        self.baseline_mode = QComboBox(); self.baseline_mode.addItems(["自动（分析范围中位数）", "手动固定基线"])
        form.addRow("基线方式", self.baseline_mode)
        self.baseline = self.spin(-1e12, 1e12, 0, 6)
        self.baseline.setEnabled(False); form.addRow("基线值（pA）", self.baseline)
        self.amplitude = self.spin(1e-6, 1e12, 15, 6)
        form.addRow("高于基线的幅值（pA）", self.amplitude)
        self.width = self.spin(0.001, 10000, 40, 3); self.width.setSuffix(" ms")
        form.addRow("高斯窗宽（FWHM）", self.width)
        self.threshold = self.spin(0.000001, 0.999999, 0.1, 6)
        form.addRow("分簇阈值", self.threshold)
        self.window_label = QLabel(); form.addRow("采样点换算", self.window_label)
        self.run_button = QPushButton("预览寻簇")
        self.run_button.setEnabled(False)
        self.run_button.clicked.connect(self.start); layout.addWidget(self.run_button)
        batch_row = QHBoxLayout(); layout.addLayout(batch_row)
        self.batch_button = QPushButton("文件夹一键寻簇")
        self.batch_button.setToolTip("使用当前通道和参数，分析当前文件夹内每个 TDMS 的完整记录")
        self.batch_button.setEnabled(False); self.batch_button.clicked.connect(self.start_batch)
        self.cancel_batch_button = QPushButton("停止")
        self.cancel_batch_button.setEnabled(False); self.cancel_batch_button.clicked.connect(self.cancel_batch)
        batch_row.addWidget(self.batch_button, 1); batch_row.addWidget(self.cancel_batch_button)
        self.batch_progress = QProgressBar(); self.batch_progress.setVisible(False); layout.addWidget(self.batch_progress)
        self.batch_status = QLabel(""); self.batch_status.setWordWrap(True); layout.addWidget(self.batch_status)
        self.batch_errors = []
        self.status = QLabel("初始参数仅供试调，请检查幅值阈值与基线。")
        self.status.setWordWrap(True); layout.addWidget(self.status)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["簇", "起点 / s", "终点 / s", "时长 / ms", "峰数"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.currentCellChanged.connect(self.select)
        self.table.cellClicked.connect(self.select)
        layout.addWidget(self.table)
        buttons = QHBoxLayout(); layout.addLayout(buttons)
        for label, callback in (("上一簇", lambda: self.navigate(-1)), ("下一簇", lambda: self.navigate(1)),
                                ("保存当前片段", self.save)):
            button = QPushButton(label); button.clicked.connect(callback); buttons.addWidget(button)
        note = QLabel("点击候选簇定位；可用现有框选调整边界。只有点击保存才加入筛选记录，随后可在筛选记录中导出。带 * 表示接触分析范围边缘。")
        note.setWordWrap(True); layout.addWidget(note)
        self.baseline_mode.currentIndexChanged.connect(lambda index: self.baseline.setEnabled(index == 1))
        for control in (self.scope, self.baseline_mode): control.currentIndexChanged.connect(self.parameters_changed)
        for control in (self.baseline, self.amplitude, self.width, self.threshold): control.valueChanged.connect(self.parameters_changed)

    @staticmethod
    def spin(low, high, value, decimals):
        spin = QDoubleSpinBox(); spin.setDecimals(decimals); spin.setRange(low, high)
        spin.setValue(value); spin.setKeyboardTracking(False)
        return spin

    def refresh_files(self):
        if self.batch_worker is not None: self.batch_worker.cancelled.set()
        self.batch_cache.clear()
        self.file_combo.blockSignals(True)
        self.file_combo.clear()
        for path in self.window.files:
            self.file_combo.addItem(path.name)
            self.file_combo.setItemData(self.file_combo.count()-1, str(path), Qt.ToolTipRole)
        self.file_combo.blockSignals(False)
        self.sync_file_selection(self.window.file_list.currentRow())

    def sync_file_selection(self, row):
        count = self.file_combo.count()
        valid = 0 <= row < count
        self.file_combo.setCurrentIndex(row if valid else -1)
        self.file_combo.setEnabled(count > 0)
        self.previous_file_button.setEnabled(valid and row > 0)
        self.next_file_button.setEnabled(valid and row < count-1)
        self.file_position_label.setText(f"{row+1 if valid else 0} / {count}")
        self.file_combo.setToolTip(str(self.window.files[row]) if valid else "请先打开数据文件夹")

    def parameters(self):
        if self.to_pa is None:
            raise ValueError("通道单位无法换算为 pA，请先确认电流标定。")
        return {"baseline_auto": self.baseline_mode.currentIndex() == 0, "baseline": self.baseline.value() / self.to_pa,
                "amplitude": self.amplitude.value() / self.to_pa, "fwhm_ms": self.width.value(),
                "threshold": self.threshold.value(), "unit": self.unit, "scope": self.scope.currentIndex(),
                "input_unit": "pA", "native_to_pa_factor": self.to_pa}

    def parameters_changed(self, *_):
        if self.restoring_parameters: return
        self.batch_cache.clear()
        self.reset_file_names()
        self.invalidate()
        self.update_samples()

    def update_samples(self):
        channel = self.window.current_channel
        self.window_label.setText(f"{self.width.value() / (1000 * channel.dt):.2f} 点" if channel else "—")

    def invalidate(self):
        self.token += 1; self.result = None
        self.table.setRowCount(0)
        self.clear_overlays()
        self.update_buttons()
        self.status.setText("候选已清空；点击预览重新寻簇。已保存片段不受影响。")

    def clear_overlays(self):
        for plot, item in self.overlays: plot.removeItem(item)
        self.overlays.clear()

    def loaded(self):
        self.loading = False
        self.invalidate()
        unit = self.window.current_channel.unit
        self.to_pa = CURRENT_TO_PA.get(unit.strip())
        if unit.strip().casefold() in VOLTAGE_UNITS:
            self.to_pa = VOLTAGE_TO_PA
            self.unit_label.setText(f"输入使用 pA；原始通道：{unit}；已确认标定：1 V = 1000 pA")
        else:
            self.unit_label.setText(f"输入使用 pA；原始通道：{unit}" if self.to_pa is not None else
                                    f"原始通道：{unit or '未知单位'}，需确认电流标定后才能使用 pA 寻簇。")
        self.unit_label.setWordWrap(True)
        self.restoring_parameters = True
        if unit != self.unit:
            self.unit = unit
            self.amplitude.setValue(15)
            self.baseline.setValue(0)
            saved = self.window.settings.get("cluster_parameters", {}).get(unit, {})
            for key, control in (("amplitude", self.amplitude), ("baseline", self.baseline),
                                 ("fwhm_ms", self.width), ("threshold", self.threshold)):
                value = saved.get(key)
                if isinstance(value, (int, float)) and self.to_pa is not None:
                    if key in ("amplitude", "baseline"): value *= self.to_pa
                    control.setValue(value)
            self.baseline_mode.setCurrentIndex(0 if saved.get("baseline_auto", True) else 1)
        self.restoring_parameters = False
        self.update_samples()
        self.update_buttons()
        self.restore_batch_result()
        if self.batch_worker: self.set_batch_controls(True)

    def start(self):
        w = self.window
        if w.current_values is None or w.current_channel is None or self.workers or self.batch_worker or self.loading or self.to_pa is None: return
        self.invalidate()
        first, last = (0, len(w.current_values)) if self.scope.currentIndex() == 0 else w.current_indices
        w.settings.setdefault("cluster_parameters", {})[self.unit] = self.parameters()
        w._save_settings()
        worker = ClusterWorker(self.token, w.current_values[first:last], w.current_channel.dt, self.parameters(), first)
        self.workers.add(worker)
        self.update_buttons()
        worker.signals.done.connect(lambda payload: self.finished(worker, payload))
        worker.signals.failed.connect(lambda payload: self.finished(worker, payload, failed=True))
        self.run_button.setEnabled(False); self.status.setText("正在后台寻簇…")
        w.thread_pool.start(worker)

    def finished(self, worker, payload, failed=False):
        self.workers.discard(worker); self.update_buttons()
        token, result = payload
        if token != self.token: return
        if failed:
            self.status.setText(f"未完成：{result}"); return
        self.result = result
        dt = self.window.current_channel.dt
        self.table.setRowCount(len(result["rows"]))
        for i, row in enumerate(result["rows"]):
            a, b = row["start_index"], row["end_index_exclusive"]
            values = [f"{i + 1}{'*' if row['left_censored'] or row['right_censored'] else ''}",
                      f"{a * dt:.6f}", f"{b * dt:.6f}", f"{(b-a)*dt*1000:.3f}", str(row["n_seeds"])]
            for j, value in enumerate(values): self.table.setItem(i, j, QTableWidgetItem(value))
        baseline_pa = result['baseline'] * self.to_pa
        threshold_pa = (result['baseline'] + result['parameters']['amplitude']) * self.to_pa
        if self.baseline_mode.currentIndex() == 0:
            self.baseline.blockSignals(True); self.baseline.setValue(baseline_pa); self.baseline.blockSignals(False)
        self.status.setText(f"找到 {len(result['rows'])} 个候选簇；基线 {baseline_pa:.6g} pA；检测线 {threshold_pa:.6g} pA。")
        self.draw_overlays()

    def update_buttons(self):
        ready = not self.workers and not self.loading and self.to_pa is not None and self.batch_worker is None
        self.run_button.setEnabled(ready)
        if hasattr(self, "batch_button"):
            self.batch_button.setEnabled(ready and bool(self.window.files))

    def reset_file_names(self):
        for i, path in enumerate(self.window.files):
            if i < self.file_combo.count():
                self.file_combo.setItemText(i, path.name)
                self.file_combo.setItemData(i, str(path), Qt.ToolTipRole)

    def set_batch_controls(self, running):
        for control in (self.scope, self.baseline_mode, self.amplitude, self.width, self.threshold):
            control.setEnabled(not running)
        self.baseline.setEnabled(not running and self.baseline_mode.currentIndex() == 1)
        self.cancel_batch_button.setEnabled(running)
        self.update_buttons()

    def start_batch(self):
        w = self.window
        if self.batch_worker or self.workers or self.loading or self.to_pa is None or not w.files or w.current_channel is None: return
        self.scope.setCurrentIndex(0)
        self.invalidate(); self.batch_cache.clear(); self.reset_file_names(); self.batch_errors = []
        parameters = self.parameters()
        w.settings.setdefault("cluster_parameters", {})[self.unit] = parameters; w._save_settings()
        parameters = dict(parameters, amplitude=self.amplitude.value(), baseline=self.baseline.value())
        worker = BatchClusterWorker(list(w.files), w.current_channel.key, parameters)
        self.batch_worker = worker
        self.batch_folder = w.data_folder
        self.batch_progress.setRange(0, len(w.files)); self.batch_progress.setValue(0); self.batch_progress.show()
        self.batch_status.setText(f"正在分析 {len(w.files)} 个文件的完整记录…")
        self.batch_status.setToolTip("")
        self.set_batch_controls(True)
        worker.signals.item.connect(lambda result: self.batch_item(worker, result))
        worker.signals.done.connect(lambda result: self.batch_done(worker, result))
        w.thread_pool.start(worker)

    def cancel_batch(self):
        if self.batch_worker:
            self.batch_worker.cancelled.set()
            self.cancel_batch_button.setEnabled(False)
            self.batch_status.setText("正在停止；已完成文件的候选会保留。")

    def batch_item(self, worker, payload):
        if worker is not self.batch_worker or self.window.data_folder != self.batch_folder or worker.cancelled.is_set(): return
        path = payload["path"]
        self.batch_progress.setValue(payload["index"])
        index = payload["index"] - 1
        if "error" in payload:
            self.batch_errors.append(f"{path.name}：{payload['error']}")
            self.file_combo.setItemText(index, f"{path.name} [失败]")
            self.file_combo.setItemData(index, self.batch_errors[-1], Qt.ToolTipRole)
        else:
            self.batch_cache[(str(path.resolve()), payload["channel"])] = payload
            count = len(payload["result"]["rows"])
            self.file_combo.setItemText(index, f"{path.name} [{count} 簇]")
            if not self.loading and path == self.window.current_path: self.restore_batch_result()
        self.batch_status.setText(f"已处理 {payload['index']} / {len(worker.files)}：{path.name}；失败 {len(self.batch_errors)}")
        self.batch_status.setToolTip("\n".join(self.batch_errors))

    def batch_done(self, worker, result):
        if worker is not self.batch_worker: return
        self.batch_worker = None; self.set_batch_controls(False)
        if self.window.data_folder != self.batch_folder:
            self.batch_status.setText("已切换文件夹，原批量任务已停止。")
            return
        completed = len(self.batch_cache)
        self.batch_status.setText(f"{'已停止' if result['cancelled'] else '寻簇完成'}：成功 {completed} 个文件，失败 {len(self.batch_errors)} 个。切换文件即可查看候选。"
                                 + (f"\n最近错误：{self.batch_errors[-1]}" if self.batch_errors else ""))

    def restore_batch_result(self):
        w = self.window
        if w.current_path is None or w.current_channel is None: return
        key = (str(w.current_path.resolve()), w.current_channel.key)
        entry = self.batch_cache.get(key)
        if entry is None: return
        try:
            if file_stamp(w.current_path) != entry["stamp"]:
                self.batch_cache.pop(key, None)
                row = w.file_list.currentRow()
                if row >= 0: self.file_combo.setItemText(row, w.current_path.name)
                self.status.setText("文件已更新，请重新寻簇。")
                return
        except OSError:
            return
        result = entry["result"]; parameters = result["parameters"]
        self.restoring_parameters = True
        self.scope.setCurrentIndex(0)
        self.baseline_mode.setCurrentIndex(0 if parameters["baseline_auto"] else 1)
        self.amplitude.setValue(parameters["amplitude"] * self.to_pa)
        self.baseline.setValue(parameters["baseline"] * self.to_pa)
        self.width.setValue(parameters["fwhm_ms"]); self.threshold.setValue(parameters["threshold"])
        self.restoring_parameters = False
        self.clear_overlays()
        self.finished(None, (self.token, result))
        if self.batch_worker: self.set_batch_controls(True)

    def draw_overlays(self):
        self.clear_overlays()
        if not self.result: return
        w = self.window; dt = w.current_channel.dt
        # Draw intervals in one graphics item per plot, keeping large candidate sets responsive.
        for plot in (w.overview_plot, w.detail_plot):
            item = ClusterBands(self.result["rows"], dt, self.choose_row)
            plot.addItem(item, ignoreBounds=True); self.overlays.append((plot, item))
            line = pg.InfiniteLine(pos=self.result["baseline"] + self.result["parameters"]["amplitude"],
                                   angle=0, pen=pg.mkPen("#E5A93D", style=Qt.DashLine))
            plot.addItem(line, ignoreBounds=True); self.overlays.append((plot, line))

    def select(self, row, *_):
        if not self.result or not 0 <= row < len(self.result["rows"]): return
        record = self.result["rows"][row]; w = self.window; dt = w.current_channel.dt
        start, end = record["start_index"] * dt, record["end_index_exclusive"] * dt
        w.region.setRegion((start, min(end, (len(w.current_values)-1)*dt)))
        w.on_region_changed()
        # Context is display-only; the overview region and saved indices remain the candidate.
        margin = max((end-start)*0.2, dt*4)
        left, right = max(0, start-margin), min((len(w.current_values)-1)*dt, end+margin)
        first, last = max(0, int(left/dt)), min(len(w.current_values), int(right/dt)+1)
        x, y = minmax_envelope(w.current_values[first:last], dt, start_index=first, max_bins=8000)
        w.detail_curve.setData(x, y)
        w.detail_plot.setXRange(left, right, padding=0)
        bounds = w.detail_amplitude_bounds(w.detail_view_box.viewRange()[0])
        if bounds: w.detail_plot.setYRange(*bounds, padding=0)

    def navigate(self, direction):
        if self.table.rowCount(): self.table.selectRow(max(0, min(self.table.rowCount()-1, self.table.currentRow()+direction)))

    def choose_row(self, row):
        if self.table.currentRow() == row: self.select(row)
        else: self.table.selectRow(row)

    def save(self):
        if self.result is None or self.table.currentRow() < 0: return
        self.window.add_current_region()


class ClusterBands(pg.GraphicsObject):
    def __init__(self, rows, dt, select):
        super().__init__()
        self.intervals = [(r["start_index"]*dt, r["end_index_exclusive"]*dt) for r in rows]
        self.select = select
        self.setZValue(-5)

    def boundingRect(self):
        from PySide6.QtCore import QRectF
        return QRectF(self.viewRect()) if self.getViewBox() else QRectF()

    def paint(self, painter, *_):
        from PySide6.QtCore import QRectF
        rect = self.viewRect()
        painter.setPen(Qt.NoPen); painter.setBrush(pg.mkBrush(65, 165, 180, 45))
        for a, b in self.intervals:
            if b >= rect.left() and a <= rect.right():
                painter.drawRect(QRectF(max(a, rect.left()), rect.top(), min(b, rect.right())-max(a, rect.left()), rect.height()))

    def viewRangeChanged(self):
        self.prepareGeometryChange(); self.update()

    def mouseClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            for i, (a, b) in enumerate(self.intervals):
                if a <= event.pos().x() < b:
                    event.accept(); self.select(i); return
        event.ignore()
