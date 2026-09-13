"""Input widgets that leave the mouse wheel available for page scrolling."""

from PySide6.QtCore import QPointF
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QAbstractScrollArea, QComboBox, QDoubleSpinBox, QSpinBox


def forward_wheel_to_scroll_area(widget, event):
    parent = widget.parentWidget()
    while parent is not None and not isinstance(parent, QAbstractScrollArea):
        parent = parent.parentWidget()
    if parent is None:
        event.ignore()
        return
    viewport = parent.viewport()
    position = QPointF(viewport.mapFromGlobal(event.globalPosition().toPoint()))
    forwarded = QWheelEvent(
        position, event.globalPosition(), event.pixelDelta(), event.angleDelta(),
        event.buttons(), event.modifiers(), event.phase(), event.inverted(),
    )
    QApplication.sendEvent(viewport, forwarded)
    event.accept()


class WheelSafeComboBox(QComboBox):
    def wheelEvent(self, event):
        forward_wheel_to_scroll_area(self, event)


class WheelSafeDoubleSpinBox(QDoubleSpinBox):
    def wheelEvent(self, event):
        forward_wheel_to_scroll_area(self, event)


class WheelSafeSpinBox(QSpinBox):
    def wheelEvent(self, event):
        forward_wheel_to_scroll_area(self, event)
