# Release Guide

## Before publishing

1. Confirm the repository links in `pyproject.toml` and `CITATION.cff` point to the intended GitHub account.
2. Confirm the copyright holder in `LICENSE`.
3. Run `pytest` and `ruff check .`.
4. Confirm `git status` does not include `user_data`, TDMS files, or experimental exports.
5. Update `src/tdms_fingerprint_viewer/__init__.py` and `CHANGELOG.md` with the same version.

## Local Windows build

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_windows.ps1
```

Outputs are written under `release/`. If Inno Setup 6 is installed, the script also builds an installer. The installer offers a desktop shortcut task and always creates a Start Menu entry.

## GitHub release

Push a semantic-version tag:

```powershell
git tag v2.3.1
git push origin v2.3.1
```

The release workflow builds on a clean Windows runner, uploads artifacts, and creates the GitHub Release for version tags.

## Code signing

Unsigned executables may trigger SmartScreen or antivirus warnings. For a wider public release, obtain an Authenticode certificate, store it as protected GitHub secrets, sign both the application executable and installer, and timestamp the signatures before publishing.
