<p align="right">
  <a href="./README.md">简体中文</a> · <strong>English</strong>
</p>

# TDMS Viewer / TDMS Molecular Fingerprint Screener

A Windows desktop application for scanning tunnelling microscopy (STM) I–t signals. It browses TDMS data, locates candidate pulse clusters, supports manual interval review, analyzes spectra, and exports raw waveforms.

[![CI](https://github.com/xiangjie208-art/tdms-viewer/actions/workflows/ci.yml/badge.svg)](https://github.com/xiangjie208-art/tdms-viewer/actions/workflows/ci.yml)
[![Latest release](https://img.shields.io/github/v/release/xiangjie208-art/tdms-viewer)](https://github.com/xiangjie208-art/tdms-viewer/releases/latest)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

> This application is intended for data preview and preliminary screening. Candidate boundaries depend on detection parameters and must not be interpreted directly as molecular dwell times. The output alone does not establish molecular identity.

## Features

### Waveform browsing and interaction

- Loads every `.tdms` file in a folder and sorts files naturally by acquisition number.
- Displays the full-record overview, local waveform, and spectrum together.
- Supports time-only, vertical-axis, and rectangular selection with the left mouse button; right-drag pans and the wheel zooms.
- Caps vertical zoom-out at the visible data extrema plus 20% margins while time zoom-out continues.
- Provides precise start, end, and duration controls in seconds or milliseconds.
- Uses draggable splitters for panel sizing, a collapsible configuration panel, and persistent layouts.

### Automatic clustering and manual review

- Generates candidate clusters with spike detection and Gaussian summation adapted from recognition-tunnelling literature.
- Exposes baseline, amplitude threshold, Gaussian width (FWHM), and grouping threshold controls.
- Uses pA for baseline and amplitude inputs. V/Volt/Volts channels use the current instrument calibration `1 V = 1000 pA`.
- Runs on the current file or processes every TDMS file in the folder with one action.
- Reports batch progress and failures, supports cancellation, and caches candidates per file for review.
- Switches files and candidates directly from the clustering page; final intervals can be adjusted before saving.
- Clustering creates candidates only. An interval enters the screening records only after manual confirmation.

### Spectrum, records, and export

- Supports FFT amplitude spectra and Welch power spectral density with Hann, Hamming, Blackman, and rectangular windows.
- Shows 0–1000 Hz on linear frequency and amplitude axes by default, with adjustable ranges and optional logarithmic axes.
- Samples up to 10 blank records and overlays their median spectrum and interquartile range.
- Provides candidate, review, no-feature, noisy, and excluded labels with notes.
- Exports raw I–t CSV, per-signal CSV, feature summaries, PNG figures, session JSON, and HTML reports.
- Produces white-background scientific figures with thin black lines, inward ticks, and no grid by default.
- Saves progress automatically and supports named sessions, backup recovery, and relocated data folders.
- Includes dark, light, and custom themes with configurable display grids and line widths.

## Download and run

### Windows release (recommended)

Download from [GitHub Releases](https://github.com/xiangjie208-art/tdms-viewer/releases/latest):

- `TDMS-Viewer-Setup-x64.exe`: Windows 64-bit installer.
- `TDMS-Viewer-Windows-x64.zip`: portable package; extract it and run `TDMS-Viewer.exe` without installing Python.
- `SHA256SUMS.txt`: SHA-256 checksums for the release files.

The binaries are not commercially code-signed, so Windows SmartScreen may report an unknown publisher. Download them from this repository's Releases page and verify the checksum.

### Run from source

Python 3.10–3.13 is required:

```powershell
python -m pip install -e .
python run_tdms_viewer.py
```

## Workflow

1. Select a folder containing TDMS files and verify the active channel and unit.
2. Select a local interval in the overview, or open the **Automatic Clustering** page and configure detection parameters.
3. Run **Preview Clusters** for one file or **Cluster Entire Folder** for batch detection.
4. Review candidates one by one and adjust final boundaries with the waveform selection tools.
5. Save confirmed intervals and add file labels or notes.
6. Select records on the **Screening Records** page and export raw waveforms, figures, and session data.

Batch candidates are cached only for the current application run and must be recomputed after restart. Confirmed screening records remain in the session.

## Clustering method

The application identifies spikes in continuous regions above the baseline plus amplitude threshold. It places a unit-height Gaussian at each spike and sums the Gaussian traces. Continuous regions where the sum exceeds the grouping threshold become candidate clusters.

The implementation uses an adjustable FWHM and explicit engineering boundary rules; it is not an exact reproduction of the authors' research code. It is intended for relatively stable baselines and upward pulses. Batch analysis applies the same controls to all files, while automatic baselines are estimated independently for each file.

See the [Chinese user guide](docs/USER_GUIDE.md) for detailed operation notes.

## Keyboard shortcuts

| Shortcut | Action |
|---|---|
| `←` / `→` | Move the local window by 25% of its width |
| `Shift + ←` / `Shift + →` | Move by 5% |
| `Ctrl + ←` / `Ctrl + →` | Narrow / widen the local window |
| `↑` / `↓` | Previous / next TDMS file |
| `A` / `R` / `X` | Candidate / review / exclude |
| `S` | Save the current interval |
| `F` | Toggle local / full-record FFT |
| `Space` | Show / hide the blank reference |
| `Ctrl + E` | Export screening results |

## Data and privacy

- Processing is local. TDMS files and screening records are not uploaded.
- Local application state is stored under `user_data`, which is excluded from Git.
- TDMS files, snapshots, notes, experimental paths, and exports should not be committed to the public repository.
- Release packages do not contain `user_data` or real experimental data.

See the [privacy notes](docs/PRIVACY.md).

## Development

```powershell
python -m pip install -e ".[dev]"
pytest
ruff check .
```

Build the Windows release locally:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_windows.ps1
```

Pushing a `v*` tag runs the GitHub Actions tests, builds the installer and portable archive, and generates SHA-256 checksums. See the [release guide](docs/RELEASE.md).

## License

[MIT License](LICENSE)
