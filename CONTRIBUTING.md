# Contributing

Thanks for your interest! Quick notes:
- Use Python **3.9+**.
- Run `ruff`/`flake8`, `mypy`, and tests before pushing.
- For non-trivial changes, open an issue first.

### Dev setup
```bash
python -m venv .venv && source .venv/bin/activate
python -m pip install -U pip
pip install -e .[dev]
pytest
```

### Commit style
- Keep commits small & focused.
- Include tests for behavior changes.
- Update `CHANGELOG.md` under **Unreleased**.
