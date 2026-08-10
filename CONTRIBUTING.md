# Contributing

1. Create a branch from `main`.
2. Install the development environment with `python -m pip install -e ".[dev]"`.
3. Run `pytest` and `ruff check .` before opening a pull request.
4. Do not commit TDMS recordings, exported screening results, local notes, absolute experimental paths, or `user_data`.

Bug reports should include the application version, Windows version, TDMS channel metadata, and a minimal anonymized reproduction when possible. Do not attach confidential experimental data unless you are authorized to publish it.
