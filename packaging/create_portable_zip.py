"""Create a privacy-safe portable release archive on Windows."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import time
import zipfile


SENSITIVE_SUFFIXES = {".tdms", ".tdms_index"}


def _is_private(relative_path: Path) -> bool:
    parts = {part.lower() for part in relative_path.parts}
    if "user_data" in parts and len(relative_path.parts) > 2:
        return True
    return relative_path.suffix.lower() in SENSITIVE_SUFFIXES


def _write_file_with_retry(
    archive: zipfile.ZipFile,
    source: Path,
    archive_name: str,
    attempts: int = 6,
) -> None:
    for attempt in range(1, attempts + 1):
        try:
            archive.write(source, archive_name)
            return
        except PermissionError:
            if attempt == attempts:
                raise
            time.sleep(0.25 * attempt)


def create_archive(source_dir: Path, destination: Path) -> None:
    source_dir = source_dir.resolve(strict=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.unlink(missing_ok=True)

    root_name = source_dir.name
    with zipfile.ZipFile(
        temporary,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
        allowZip64=True,
    ) as archive:
        archive.writestr(f"{root_name}/user_data/", b"")
        for source in sorted(source_dir.rglob("*")):
            relative = source.relative_to(source_dir)
            if _is_private(Path(root_name) / relative):
                continue
            archive_name = (Path(root_name) / relative).as_posix()
            if source.is_dir():
                if relative.parts != ("user_data",):
                    archive.writestr(f"{archive_name}/", b"")
                continue
            _write_file_with_retry(archive, source, archive_name)

    os.replace(temporary, destination)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    create_archive(args.source, args.destination)


if __name__ == "__main__":
    main()
