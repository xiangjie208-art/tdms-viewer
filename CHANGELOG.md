# Changelog

All notable changes are documented here. This project follows semantic versioning.

## [Unreleased]

## [2.6.1] - 2026-09-05

- Fixed local-waveform panning and horizontal zoom to reveal adjacent data and synchronize the overview selection, time controls, statistics, and local spectrum.
- Kept local navigation within file boundaries and preserved the time-window width during repeated drags.

## [2.6.0] - 2026-08-12

- Added an export-content dialog for independently selecting CSV totals, per-signal CSV files, image types, session JSON, and HTML reports.
- Added one traceable CSV child table per saved signal while retaining `feature.csv` and `I-T_raw_data.csv` summary tables.
- Organized result bundles into `summary/`, `signals/`, and `images/`, creating only the directories selected for export.
- Added remembered export preferences, select-all/clear-all actions, and validation that at least one output is selected.

## [2.5.0] - 2026-08-11

- Added a vertically stacked global/local I–T combination image to current-image and screening-result exports.
- Added resumable processing sessions with automatic mark/note drafts, last-file/channel restoration, and analysis-setting restoration.
- Added named session save/open controls, portable JSON session files, data-folder relocation, atomic writes, and `.bak` recovery.
- Migrated legacy sessions to relative TDMS file identifiers so moved datasets can be rebound safely.

## [2.4.0] - 2026-08-11

- Added Ctrl/Shift multi-selection for batch deletion and selected-region export.
- Renamed the region summary export to `feature.csv` and removed `file_marks.csv` from result bundles.
- Added `I-T_raw_data.csv` with original time/current samples for every exported interval.
- Renamed exported snapshots using the source file, interval, note, and plot type.

## [2.3.1] - 2026-08-10

- Fixed GitHub Actions installer builds when the optional Inno Setup Simplified Chinese language file is unavailable.
- Added immediate error handling for failed packaging commands.
- Updated official GitHub Actions to their Node.js 24-compatible major versions.
- Fixed portable settings storage so source and frozen builds consistently use the configured private data directory.

## [2.3.0] - 2026-08-10

- Reorganized the project into a standard `src/` Python package.
- Added privacy-safe Git exclusions for TDMS files, screening records, notes, and snapshots.
- Added unit tests, GitHub Actions CI, Windows portable build, and installer definitions.
- Added portable, installed, and frozen-application data-directory handling.
- Added Windows icon generation and installer-created desktop/Start Menu shortcuts.

## [2.2.0] - 2026-08-06

- Added exact local start, end, and duration controls with seconds/milliseconds units.

## [2.1.0] - 2026-08-06

- Restored the original four-panel/two-tab workflow and export functions.
- Added dark/light/custom plot themes and keyboard region navigation.
