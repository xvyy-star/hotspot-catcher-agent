# Contributing

Contribute only code, tests and assets that you have the right to distribute.
Contributions are made under this project's MIT license. Keep upstream notices
for any copied or adapted material and describe its origin in the pull request.

Never include API keys, account identifiers, `.env` files, local configuration,
collected datasets, database exports, screenshots of private data or credentials.
Use clearly synthetic test fixtures and reserved example domains.

## Checks

Install `backend/requirements-dev.txt`, then run `python -m pytest backend/tests`.
Tests use temporary SQLite, an in-memory Redis implementation and mocked HTTP.
MySQL migration checks are separate in CI.

From `frontend/`, run `npm ci`, `npm run build`, and `npm run test:e2e:mock`.
Playwright requires its Chromium installation or a configured local executable.

Before committing, run `python scripts/check_public_release.py` to inspect the
Git index. This check reports file paths and rule names, never secret values.
