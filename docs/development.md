# Development

## Setup

You need [uv](https://docs.astral.sh/uv/) and Python 3.11 or newer.

```bash
git clone https://github.com/DominikLudwig1995/ZaehlerAgent && cd ZaehlerAgent
uv sync
uv run python scripts/demo.py        # a running agent with a fake camera and fake models, no API key needed
```

Run against your own setup:

```bash
CONFIG_FILE=config/config.yml LLM_API_KEY=... uv run uvicorn app.main:app --reload --port 8000
```

## Checks

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy app
uv run pytest            # coverage is measured, the build fails below 90 %
```

`pre-commit install` runs the same linters and a check for mangled umlauts (`scripts/check_mojibake.py`) before
every commit. CI runs everything on GitHub Actions, plus a `docker compose` smoke test and a Trivy scan of the image.

## Dependencies

Version updates (Python packages, Docker base images, GitHub Actions) come from Renovate on the maintainer's
server and arrive through the normal release flow. GitHub's Dependabot *security* updates and alerts stay on.

## Layout

```
app/
  main.py          FastAPI app: API, pages, Prometheus endpoint, settings endpoints
  service.py       the polling loop, one reading, reconfiguration at runtime
  vision.py        picture preparation and the OpenAI-compatible model client
  plausibility.py  vote and plausibility check (pure functions, the heart of it)
  config.py        settings: file, environment, UI overrides, validation
  mqtt_ha.py       MQTT publisher and Home Assistant discovery
  storage.py       SQLite history
  metrics.py       Prometheus text format
  static/          the web UI (one HTML file, no build step, no dependencies)
tests/             unit and API tests, respx for HTTP, no network
scripts/           demo.py, check_mojibake.py
docs/              the documentation you are reading
deploy/            an example Nomad job and its deploy script
```

Design rules: the plausibility check stays a pure function of its inputs; the UI has no build step; no setting
without a test; a camera is never hit in parallel.

## Tests

Tests do not need a network or a camera. HTTP is mocked with respx, MQTT with a fake publisher, the FastAPI app is
driven with `TestClient`. When you add a setting, add it to `config.py` validation, to the UI form and to
`tests/test_ui_config.py`.

## Releases

1. Update [`CHANGELOG.md`](../CHANGELOG.md) (new section `## [x.y.z] - date`) and `version` in `pyproject.toml`.
2. Merge to `main`, tag `vx.y.z` and push the tag.
3. The *Release* workflow builds the image for amd64 and arm64, pushes it to `ghcr.io`, and creates the GitHub
   release with the notes of that section of the changelog.

Versioning follows [semver](https://semver.org): a change to an API endpoint, a setting name or the config format that
breaks existing setups is a major version and is called out at the top of the changelog entry.
