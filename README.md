<p align="right">
  <strong>简体中文</strong> · <a href="./README_EN.md">English</a>
</p>

# TDMS Viewer / TDMS 分子指纹筛选器

面向扫描隧道显微镜（STM）I–t 信号的 Windows 桌面工具，用于浏览 TDMS 数据、定位候选脉冲簇、人工复核片段、分析频谱并导出原始波形。

[![CI](https://github.com/xiangjie208-art/tdms-viewer/actions/workflows/ci.yml/badge.svg)](https://github.com/xiangjie208-art/tdms-viewer/actions/workflows/ci.yml)
[![Latest release](https://img.shields.io/github/v/release/xiangjie208-art/tdms-viewer)](https://github.com/xiangjie208-art/tdms-viewer/releases/latest)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

> 从长时间 I–t 数据浏览、候选簇定位到人工复核与原始波形导出，TDMS Viewer 提供完整的本地分析工作流。

## 主要功能

### 波形浏览与交互

- 批量读取文件夹内的 `.tdms` 文件，并按采集编号自然排序。
- 同步显示完整数据总览、局部波形和频谱。
- 左键支持时间、纵轴及矩形框选；右键拖动平移；滚轮缩放。
- 局部图向外缩小时，纵轴限制在可见数据范围上下各 20% 留白内，横轴继续缩放。
- 可精确设置局部窗口起点、终点和宽度，并在秒与毫秒之间切换。
- 可拖动分隔线调整各区域宽高，收起配置栏并保存当前布局。

### 自动寻簇与人工复核

- 使用尖峰检测和高斯叠加方法生成候选簇，方法借鉴识别隧穿文献。
- 可调整基线、幅值阈值、高斯窗宽（FWHM）和分簇阈值。
- 基线和幅值参数统一使用 pA；V/Volt/Volts 通道采用当前仪器标定 `1 V = 1000 pA`。
- 支持当前文件预览，也可对文件夹内全部 TDMS 一键寻簇。
- 批量任务提供进度、停止、失败记录和逐文件候选缓存。
- 可在寻簇页直接切换文件和候选簇，重新框选后保存最终片段。
- 自动寻簇生成候选，人工确认后的片段进入筛选记录。

### 频谱、记录与导出

- 支持 FFT 幅度谱和 Welch 功率谱密度，以及 Hann、Hamming、Blackman 和矩形窗。
- 频谱默认使用线性坐标显示 0–1000 Hz，可调整显示范围或启用对数坐标。
- 可从空白文件夹抽取最多 10 条记录，叠加中位频谱和四分位范围。
- 支持候选、待复查、无明显特征、噪声过大和排除等标记及备注。
- 可导出原始 I–t CSV、逐信号 CSV、特征汇总、PNG、会话 JSON 和 HTML 报告。
- 默认图片采用白底、黑色细线、向内刻度和无网格的科研绘图样式。
- 自动保存处理进度，支持命名会话、备份恢复和数据目录重定位。
- 提供深色、浅色和自定义主题，可控制界面网格与线宽。

## 获取与运行

### Windows 版本（推荐）

从 [GitHub Releases](https://github.com/xiangjie208-art/tdms-viewer/releases/latest) 下载：

- `TDMS-Viewer-Setup-x64.exe`：Windows 64 位安装程序。
- `TDMS-Viewer-Windows-x64.zip`：解压后运行 `TDMS-Viewer.exe`，无需安装 Python。
- `SHA256SUMS.txt`：发布文件的 SHA-256 校验值。

推荐从本仓库的 Releases 页面下载，并使用随附的 SHA-256 校验值确认文件完整性。

### 从源码运行

需要 Python 3.10–3.13：

```powershell
python -m pip install -e .
python run_tdms_viewer.py
```

## 使用流程

1. 选择包含 TDMS 文件的数据文件夹，并确认数据通道和单位。
2. 在总览中框选局部区间，或打开“自动寻簇”页设置参数。
3. 点击“预览寻簇”分析当前文件，或点击“文件夹一键寻簇”完成批量检测。
4. 在候选列表中逐簇查看，使用波形框选工具修正最终边界。
5. 保存确认片段，并添加文件标记或备注。
6. 在“筛选记录”页多选需要的片段，导出原始波形、图片和会话记录。

批量候选采用运行期缓存，已确认的筛选记录随会话持续保存。

## 寻簇方法说明

程序先从连续超过“基线＋幅值阈值”的区间中选取尖峰，再在尖峰位置叠加单位峰高的高斯窗。高斯叠加结果超过分簇阈值的连续区间被标记为候选簇。

当前实现将识别隧穿文献中的高斯叠加思路转化为可调 FWHM 和明确的工程边界规则，适用于基线较稳定、以向上脉冲为主的数据。批量分析统一使用所选参数，并为每个文件独立估计自动基线。

详细说明见[用户指南](docs/USER_GUIDE.md)。

## 快捷键

| 快捷键 | 功能 |
|---|---|
| `←` / `→` | 将局部窗口移动其宽度的 25% |
| `Shift + ←` / `Shift + →` | 精细移动 5% |
| `Ctrl + ←` / `Ctrl + →` | 缩窄 / 加宽局部窗口 |
| `↑` / `↓` | 上一个 / 下一个 TDMS 文件 |
| `A` / `R` / `X` | 候选 / 待复查 / 排除 |
| `S` | 保存当前区间 |
| `F` | 切换局部 / 完整 FFT |
| `Space` | 显示 / 隐藏空白参考 |
| `Ctrl + E` | 导出筛选结果 |

## 数据与隐私

- 所有 TDMS 数据与筛选记录均在本地处理和保存。
- 本地状态保存在 `user_data`，该目录已被 Git 排除。
- 公开仓库聚焦程序代码和项目文档，实验数据、快照、备注与导出结果保留在本机。
- 发布构建包含运行程序和配套文档，保持实验数据与软件分离。

详见[隐私说明](docs/PRIVACY.md)。

## 开发

```powershell
python -m pip install -e ".[dev]"
pytest
ruff check .
```

构建 Windows 发布包：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_windows.ps1
```

推送 `v*` 标签后，GitHub Actions 会执行测试，构建安装程序和便携版，并生成 SHA-256 校验文件。详见[发布说明](docs/RELEASE.md)。

## License

[MIT License](LICENSE)
