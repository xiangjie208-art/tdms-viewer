"""Resizable four-panel workspace with persistent splitter proportions."""
from PySide6.QtCore import QByteArray, Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QPushButton


class LayoutWorkspace(QWidget):
    def __init__(self):
        super().__init__()
        self.controls_hidden = False
        self.expanded_top = None
        layout = QVBoxLayout(self); layout.setContentsMargins(7, 7, 7, 7); layout.setSpacing(4)
        toolbar = QHBoxLayout(); layout.addLayout(toolbar)
        self.controls_button = QPushButton("收起配置栏")
        self.controls_button.clicked.connect(self.toggle_controls)
        self.reset_button = QPushButton("恢复默认布局")
        self.reset_button.clicked.connect(self.reset_layout)
        toolbar.addWidget(self.controls_button); toolbar.addStretch(1); toolbar.addWidget(self.reset_button)
        self.vertical = QSplitter(Qt.Vertical)
        self.top = QSplitter(Qt.Horizontal); self.bottom = QSplitter(Qt.Horizontal)
        self.vertical.addWidget(self.top); self.vertical.addWidget(self.bottom)
        self.splitters = (self.vertical, self.top, self.bottom)
        for splitter in self.splitters:
            splitter.setChildrenCollapsible(False); splitter.setHandleWidth(7)
            splitter.setStyleSheet("QSplitter::handle { background: #D9DEE5; } QSplitter::handle:hover { background: #8AAED1; }")
        layout.addWidget(self.vertical, 1)

    def setup(self, controls, overview, detail, spectrum):
        self.panels = {"controls": controls, "overview": overview, "detail": detail, "spectrum": spectrum}
        self.top.addWidget(controls); self.top.addWidget(overview)
        self.bottom.addWidget(detail); self.bottom.addWidget(spectrum)
        for widget in self.panels.values(): widget.setMinimumSize(120, 90)
        self.reset_layout()


    def states(self):
        return [bytes(s.saveState().toBase64()).decode("ascii") for s in self.splitters]

    def apply_states(self, states):
        if not isinstance(states, list) or len(states) != 3: return
        for splitter, state in zip(self.splitters, states):
            if isinstance(state, str):
                splitter.restoreState(QByteArray.fromBase64(state.encode("ascii", errors="ignore")))




    def toggle_controls(self):
        if not self.controls_hidden:
            self.expanded_top = self.states()[1]
        self.controls_hidden = not self.controls_hidden
        self.panels["controls"].setVisible(not self.controls_hidden)
        if not self.controls_hidden and self.expanded_top:
            self.top.restoreState(QByteArray.fromBase64(self.expanded_top.encode("ascii")))
        self.controls_button.setText("展开配置栏" if self.controls_hidden else "收起配置栏")

    def reset_layout(self):
        self.controls_hidden = False; self.expanded_top = None
        self.top.show(); self.bottom.show()
        for panel in self.panels.values(): panel.show()
        self.controls_button.setText("收起配置栏")
        self.vertical.setSizes([430, 570]); self.top.setSizes([340, 660]); self.bottom.setSizes([340, 660])

    def capture(self):
        return {"states": self.states(),
                "controls_hidden": self.controls_hidden, "expanded_top": self.expanded_top}

    def restore(self, settings):
        if not isinstance(settings, dict): return
        self.apply_states(settings.get("states"))
        self.controls_hidden = bool(settings.get("controls_hidden", False))
        self.expanded_top = settings.get("expanded_top") if isinstance(settings.get("expanded_top"), str) else None
        self.panels["controls"].setVisible(not self.controls_hidden)
        self.controls_button.setText("展开配置栏" if self.controls_hidden else "收起配置栏")
