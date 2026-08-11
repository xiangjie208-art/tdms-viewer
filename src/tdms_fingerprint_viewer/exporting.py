from __future__ import annotations

import csv
import json
from pathlib import Path
import re

from .core import load_trace


FEATURE_COLUMNS = [
    "file", "channel", "start_s", "end_s", "tag", "note",
    "mean", "std", "min", "max", "ptp", "peaks",
]
IT_COLUMNS = [
    "file", "channel", "start_s", "end_s", "note",
    "time_s", "current", "current_unit",
]
_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED_FILENAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


def safe_filename_component(value, fallback: str, max_length: int = 80) -> str:
    text = " ".join(str(value or "").split())
    text = _INVALID_FILENAME_CHARS.sub("_", text).strip(" .")
    text = re.sub(r"_+", "_", text)
    if not text:
        text = fallback
    if text.split(".", 1)[0].upper() in _RESERVED_FILENAMES:
        text = f"_{text}"
    return text[:max_length].rstrip(" .") or fallback


def region_export_basename(region: dict) -> str:
    source_name = region.get("file_name") or Path(region.get("file", "signal")).name
    file_stem = safe_filename_component(Path(source_name).stem, "signal")
    note = safe_filename_component(region.get("note"), "无备注")
    start = float(region.get("start_s", 0.0))
    end = float(region.get("end_s", 0.0))
    return f"{file_stem}_{start:.5f}-{end:.5f}s_{note}"


def unique_export_basename(folder: Path, basename: str, suffixes: tuple[str, ...]) -> str:
    candidate = basename
    number = 2
    while any((folder / f"{candidate}_{suffix}.png").exists() for suffix in suffixes):
        candidate = f"{basename}_{number}"
        number += 1
    return candidate


def resolve_region_file(region: dict, data_folder: Path) -> Path | None:
    stored = Path(region.get("file", ""))
    file_name = region.get("file_name") or stored.name
    candidates = (stored, data_folder / file_name, data_folder / stored.name)
    return next((candidate for candidate in candidates if candidate.is_file()), None)


def region_sample_bounds(region: dict, dt: float, length: int) -> tuple[int, int]:
    if "start_index" in region and "end_index_exclusive" in region:
        start = int(region["start_index"])
        end = int(region["end_index_exclusive"])
    else:
        start = int(round(float(region.get("start_s", 0.0)) / dt))
        end = int(round(float(region.get("end_s", 0.0)) / dt)) + 1
    start = max(0, min(length, start))
    end = max(start, min(length, end))
    return start, end


def write_feature_csv(path: Path, regions: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(FEATURE_COLUMNS)
        for region in regions:
            stats = region.get("statistics", {})
            writer.writerow([
                region.get("file", ""), region.get("channel", ""),
                region.get("start_s", ""), region.get("end_s", ""),
                region.get("tag", ""), region.get("note", ""),
                stats.get("mean", ""), stats.get("std", ""),
                stats.get("min", ""), stats.get("max", ""),
                stats.get("ptp", ""),
                json.dumps(region.get("peaks", []), ensure_ascii=False),
            ])


def write_it_raw_csv(path: Path, regions: list[dict], data_folder: Path) -> tuple[int, list[str]]:
    row_count = 0
    warnings = []
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(IT_COLUMNS)
        for region in regions:
            source = resolve_region_file(region, data_folder)
            display_name = region.get("file_name") or Path(region.get("file", "")).name
            if source is None:
                warnings.append(f"找不到原始文件：{display_name}")
                continue
            try:
                values, channel, _ = load_trace(source, region.get("channel") or None)
            except Exception as exc:
                warnings.append(f"无法读取 {display_name}：{exc}")
                continue
            requested_channel = region.get("channel")
            if requested_channel and channel.key != requested_channel:
                warnings.append(f"找不到原通道：{display_name} / {requested_channel}")
                continue
            start, end = region_sample_bounds(region, channel.dt, len(values))
            for index in range(start, end):
                writer.writerow([
                    display_name, channel.key,
                    region.get("start_s", ""), region.get("end_s", ""),
                    region.get("note", ""), index * channel.dt,
                    float(values[index]), channel.unit,
                ])
            row_count += end - start
    return row_count, warnings
