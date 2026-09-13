# Changelog

All notable changes are documented here. This project follows semantic versioning.

## [Unreleased]

- Reframed the bilingual project overview and clustering guide around product capabilities, workflow, and intended data conditions.
- Added linked Chinese and English README pages and updated the repository overview for clustering, batch review, flexible layouts, and scientific figure exports.
## [2.10.0] - 2026-09-12

- Added draggable workspace splitters, a collapsible configuration panel, layout persistence, and a default-layout reset.
- Added one-click folder-wide clustering with sequential background processing, per-file unit conversion, progress, cancellation, error reporting, and candidate caching for file-to-file review.
- Added TDMS file navigation directly in the cluster panel, with previous/next file buttons, a filename selector, and synchronized file position.
- Enabled V/Volt/Volts cluster previews with the configured instrument calibration of 1 V = 1000 pA, recording the conversion factor alongside saved detection parameters.
- Simplified plot tooltips and cluster-panel guidance to concise product language.
- Displayed cluster baseline and amplitude-threshold inputs in pA, with native-current-unit conversion and explicit handling of uncalibrated voltage channels.
- Added background Gaussian cluster previews with adjustable pA amplitude threshold, FWHM, grouping threshold, baseline, and scope; candidate navigation and manual interval saving preserve raw samples and detection provenance.
- Included SciPy in runtime and Windows packaging dependencies for the Gaussian convolution implementation.

## [2.9.1] - 2026-09-12

- Included the new Matplotlib export dependency in Windows packages; supersedes the withdrawn 2.9.0 packages.

## [2.9.0] - 2026-09-12

- Limited local-waveform wheel zoom-out to visible data extrema with 20% vertical margins, while allowing continued time zoom-out and newly visible peaks; preserved zoom-in and manual axis selections.
- Replaced screen captures for new plot exports and region snapshots with fixed-size white scientific figures, thin black curves, inward ticks, boxed axes, and English axis labels with actual units. Combined figures use the same white style.

## [2.8.0] - 2026-09-11

- Added a background-grid toggle and adjustable curve width (0.2–5 pt) to display settings, applied across all plots and remembered across restarts.
- Defaulted the spectrum to 0–1000 Hz with linear frequency and amplitude axes; added a frequency-range dialog and session persistence, with sample and blank overlays restricted to the chosen display range.
- Replaced the local waveform's move-mode button with right-button dragging; left-button selection stays active and mouse-wheel zoom remains available.

## [2.7.0] - 2026-09-11

- Added compact icon controls for moving, time selection, vertical-axis selection, and rectangular selection in the local waveform panel.
- Time selection spans the full plot height and changes only the time range; vertical selection spans the full plot width and changes only the vertical range.
- Kept selection modes active for repeated selections, with translucent previews and support for reverse-direction drags.
- Preserved mouse-wheel zoom and synchronized time selections with the overview, time inputs, statistics, and local spectrum.
- Added real mouse-drag regression tests for selection geometry, independent axes, and repeated selections.

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
