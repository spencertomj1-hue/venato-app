# Contributing to Venato

Thanks for helping! Setup takes a few minutes, and a few rules keep everyone's personal data safe.

## Set up

Needs Python 3.13 and Git.

```bash
git clone https://github.com/<you>/venato-app.git && cd venato-app
python3.13 -m venv .venv && .venv/bin/pip install -r requirements.txt
./scripts/install-hooks.sh        # gitleaks pre-commit hook (see below)
```

On a Mac, `./setup.sh` does the install and also builds Venato.app. On Windows use `setup.ps1`.

## Run

```bash
.venv/bin/python scripts/seed_demo.py                       # makes a demo data folder with fake data
VENATO_DATA_DIR=<that folder> .venv/bin/streamlit run app.py  # the app in a browser
.venv/bin/python desktop.py                                  # the app in its own window
.venv/bin/python -m pytest -q -p no:logging tests           # the tests
```

## Never commit real data

Venato is a personal tracker, so a careless commit could publish someone's diary, timetable or calendar link.

- **User data never lives in the repo.** Venato stores it in its data folder (`~/Library/Application Support/Venato/` on a Mac, `%APPDATA%\Venato` on Windows), and secrets (the Outlook link, an API key) only in the macOS Keychain / Windows Credential Manager. Don't add code that writes user data or secrets into the project folder.
- **Don't commit** databases (`*.db`), calendars (`*.ics`), spreadsheets or exports (`*.csv`, `*.xlsx`), recordings, logs, `.env` files, `.streamlit/secrets.toml`, `settings.json` or `venato_config.json`. `.gitignore` blocks these, so please don't force-add them.
- **Use fake data** in tests, fixtures, screenshots and docs: obviously made-up names, places and links (e.g. `example.com`).
  - For screenshots, run the app on a demo data folder: `.venv/bin/python scripts/seed_demo.py`.
  - Tests use temporary folders via `VENATO_DATA_DIR`. Never point them at a real data folder.

## Run gitleaks before every commit

Install [gitleaks](https://github.com/gitleaks/gitleaks) (`brew install gitleaks`), then turn on the pre-commit hook once per clone:

```bash
./scripts/install-hooks.sh
```

The hook scans your staged changes and blocks the commit if it finds a secret. If you use the [pre-commit](https://pre-commit.com) framework instead, `.pre-commit-config.yaml` sets up the same check (`pre-commit install`).

Before opening a pull request, also scan the whole history of your branch:

```bash
gitleaks git . --redact
```

## Making changes

- **Read the guide first:** [`HANDOVER.md`](HANDOVER.md) explains the architecture and the gotchas.
- **Keep things simple and commented,** in the style of the surrounding code.
- **Run the tests:** `.venv/bin/python -m pytest -q -p no:logging tests`
- **Restart the app** after changing anything other than `app.py` (component JS/CSS are read at startup).

## Submit a pull request

1. Fork the repo and branch off `main` (`git checkout -b my-change`).
2. Keep each PR to one change, and add or update tests for it.
3. Run the tests and `gitleaks git . --redact`.
4. Update the README and the `[Unreleased]` section of `CHANGELOG.md` if users will notice the change.
5. Open the PR and fill in the template. CI runs the tests on Windows, macOS and Linux.
