# Contributing

Thanks for helping improve WaitLess.

## Setup
```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
pytest -q && ruff check .
```

## Workflow
1. Fork the repository and create a branch (`feature/short-description`).
2. Make your change and add or update tests in `tests/`.
3. Run `ruff check .` and `pytest -q`; both must pass.
4. Open a pull request describing what changed and why. Include a screenshot for UI changes.

## Guidelines
- Keep patient data minimal and never store camera images.
- Staff-only endpoints must use the `staff_only` decorator and respect per-hospital access.
- Use clear commit messages (for example `Add SMS alert when position <= 2`).
