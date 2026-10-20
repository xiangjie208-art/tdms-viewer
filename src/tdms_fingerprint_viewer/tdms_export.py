from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import os
from pathlib import Path
import shutil


@dataclass
class TdmsExportResult:
    copied: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def export_tdms_files(
    files: list[Path],
    destination: Path,
    progress: Callable[[int, int, str], None] | None = None,
) -> TdmsExportResult:
    """Copy complete TDMS files, preserving existing destination files."""
    result = TdmsExportResult()
    destination = Path(destination)
    total = len(files)
    for completed, source in enumerate(files, start=1):
        source = Path(source)
        target = destination / source.name
        created = False
        try:
            # lexists also protects a dangling destination symlink.
            if source.suffix.lower() != ".tdms" or os.path.lexists(target):
                result.skipped.append(source.name)
            else:
                # Read access is checked before creating any destination file.
                with source.open("rb") as reader:
                    destination.mkdir(parents=True, exist_ok=True)
                    try:
                        writer = target.open("xb")
                    except FileExistsError:
                        # Another export may have created this name meanwhile.
                        result.skipped.append(source.name)
                    else:
                        created = True
                        with writer:
                            shutil.copyfileobj(reader, writer, length=1024 * 1024)
                        try:
                            shutil.copystat(source, target)
                        except OSError:
                            # File attributes are optional; the full data is saved.
                            pass
                        result.copied.append(source.name)
        except Exception as exc:
            detail = str(exc)
            if created:
                try:
                    target.unlink()
                except OSError as cleanup_error:
                    detail += f"（部分文件清理失败：{cleanup_error}）"
            result.errors.append(f"{source.name}：{detail}")
        if progress is not None:
            progress(completed, total, source.name)
    return result
