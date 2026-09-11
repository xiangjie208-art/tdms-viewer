"""Screen-independent, white-background scientific figure exports."""

from io import BytesIO

import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.ticker import AutoMinorLocator, FormatStrFormatter, MaxNLocator
from PySide6.QtGui import QPixmap


def figure_pixmap(plot, *, xlabel, ylabel, log_x=False, log_y=False):
    figure = Figure(figsize=(7.16, 2.98), dpi=300, facecolor="white")
    FigureCanvasAgg(figure)
    ax = figure.add_subplot(111)
    figure.subplots_adjust(left=0.145, right=0.97, bottom=0.20, top=0.96)
    if log_x: ax.set_xscale("log")
    if log_y: ax.set_yscale("log")
    curves = plot.listDataItems()
    for index, curve in enumerate(curves):
        x, y = curve.xData, curve.yData
        if x is None or y is None: continue
        name = curve.name()
        is_reference = name == "空白中位数"
        label = "Blank median" if is_reference else "Sample" if name == "当前数据" else None
        ax.plot(x, y, color="0.45" if len(curves) > 1 and index > 0 else "black",
                linewidth=0.45, linestyle="--" if is_reference else "-", label=label)
        if is_reference and index >= 2:
            lower, upper = curves[index - 2], curves[index - 1]
            if lower.xData is not None and upper.xData is not None and np.array_equal(lower.xData, upper.xData):
                ax.fill_between(lower.xData, lower.yData, upper.yData, color="0.85", linewidth=0)
    bounds = plot.getViewBox().viewRange()
    xlim = np.power(10.0, bounds[0]) if log_x else bounds[0]
    ylim = np.power(10.0, bounds[1]) if log_y else bounds[1]
    ax.set_xlim(xlim); ax.set_ylim(ylim)
    for axis, logarithmic in ((ax.xaxis, log_x), (ax.yaxis, log_y)):
        if not logarithmic:
            axis.set_major_locator(MaxNLocator(nbins=3 if axis is ax.xaxis else 4, steps=[1, 2, 3, 5, 10]))
            axis.set_minor_locator(AutoMinorLocator(4))
        axis.get_offset_text().set_fontsize(10)
    if not log_y and 0.001 <= ylim[1] - ylim[0] < 1:
        step = (ylim[1] - ylim[0]) / 4
        decimals = max(0, int(np.ceil(-np.log10(step))) + 1)
        ax.yaxis.set_major_formatter(FormatStrFormatter(f"%.{decimals}f"))
    ax.set_xlabel(xlabel, fontsize=12, fontfamily="DejaVu Sans")
    ax.set_ylabel(ylabel, fontsize=12, fontfamily="DejaVu Sans")
    ax.tick_params(which="both", direction="in", top=True, right=True, labelsize=11, width=0.7)
    ax.tick_params(which="major", length=4)
    ax.tick_params(which="minor", length=2)
    for spine in ax.spines.values(): spine.set_linewidth(0.8)
    ax.grid(False)
    if any(curve.name() == "空白中位数" for curve in curves):
        ax.legend(frameon=False, fontsize=9)
    buffer = BytesIO()
    figure.savefig(buffer, format="png", dpi=300, facecolor="white")
    pixmap = QPixmap()
    pixmap.loadFromData(buffer.getvalue(), "PNG")
    figure.clear()
    return pixmap
