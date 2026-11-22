# Changelog

All notable changes are listed here. The format follows [Keep a Changelog](https://keepachangelog.com), versions
follow [semver](https://semver.org).

## [2.2.0] - 2026-11-22

First public release.

- New documentation: the README says what the project is for, the details moved to `docs/` (how it works,
  configuration, Home Assistant, deployment, API and metrics, accuracy, troubleshooting, development).
- `scripts/demo.py`: a running agent with a fake camera, fake models and seeded history, no hardware or API key.
- Contributing guide, security policy, issue and pull request templates.
- Type checking with mypy in CI, tests on Python 3.11 and 3.14, coverage must stay above 90 %.
- Fix: Prometheus metrics keep full precision. Timestamps were rounded to six digits, which made
  `zaehler_last_accepted_timestamp_seconds` off by more than an hour.
- Fix: the Home Assistant device is called `ZaehlerAgent` (was `Zähler-Agent`). Existing sensors keep their entity
  ids; only new installs get `sensor.zaehleragent_*`.
- Fix: setting a value by hand returned a stale decision when a poll ran at the same moment.

## [2.1.0] - 2026-11-21

- Every view has its own page and URL: `/`, `/meters`, `/meters/new`, `/meters/<name>` (the settings of one
  meter), `/settings`.
- Live picture on demand (`GET /api/live/{name}`), optionally with the camera's light: per meter `live_url`,
  `light_on_url`, `light_off_url`, `light_settle_seconds`. The light is switched off again even when the shot
  fails. Dashboard: *Live* button with a *light* checkbox. The meter form has a quick start for
  AI-on-the-edge cameras (`/capture`, `/lighton`, `/lightoff`).

## [2.0.0] - 2026-11-21

- Everything is configurable in the web UI: models, API key and base URL, interval, budget, MQTT, and the meters.
  Add, edit and delete cameras/meters at runtime; draw the crop on the camera picture, preview what the models
  see, test a reading before saving. Home Assistant sensors are created and removed automatically.
- UI changes are stored in `DATA_DIR/settings.json` (mode 600) and win over the config file and the environment;
  "Reset" goes back, "Download as config.yml" exports a setup without secrets.
- `READ_ONLY=true` disables every change (for a shared dashboard).
- Breaking: `Settings.from_env` and `OPENROUTER_API_KEY` as Python names are gone (the environment variable
  `OPENROUTER_API_KEY` still works as fallback for `LLM_API_KEY`). docker-compose no longer needs a config file.

## [1.2.0] - 2026-11-21

- New UI: large value, status, what each model read, curve with time axis, pictures with zoom, set-by-hand form,
  cost bar, dark mode, mobile layout.

## [1.1.0] - 2026-11-21

- `POST /api/meters/{name}/value`: set the counter by hand (start value, replaced counter).
- Image: newer zlib, no pip/setuptools at runtime (Trivy findings).

## [1.0.0] - 2026-11-21

First release.

- Reads mechanical meters (gas, water, electricity, heat, any digit-wheel counter) from a camera picture with
  vision models; the digits of several models are voted wheel by wheel.
- Plausibility check: a counter never goes down and never advances faster than `max_rate_per_hour`.
- Home Assistant sensors per meter through MQTT discovery (`total_increasing`, energy dashboard ready).
- Web UI (`/`): value, last decision, camera picture and crop, history chart, "Read now".
- Prometheus metrics (`/metrics`), history in SQLite, daily cost budget.
- Generic: any OpenAI-compatible API (OpenRouter, OpenAI, Ollama, vLLM), any camera that serves a picture URL,
  one YAML file for the config, `docker compose up -d` to run.
