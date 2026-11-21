# zaehler-agent

[![CI](https://github.com/DominikLudwig1995/zaehler-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/DominikLudwig1995/zaehler-agent/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/DominikLudwig1995/zaehler-agent)](https://github.com/DominikLudwig1995/zaehler-agent/releases)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Reads mechanical meters (gas, water, electricity, heat: digit wheels) with vision models and reports the values to Home Assistant.

## Release notes

**2.0.0** (2026-11-21): everything is configurable in the web UI, including adding and removing cameras/meters. 1.x: multi-model voting, plausibility check, Home Assistant discovery, Prometheus metrics, history, docker compose. Full list: [CHANGELOG.md](CHANGELOG.md).

Cameras (for example ESP32 with [AI-on-the-edge-device](https://github.com/jomjol/AI-on-the-edge-device)) look at the digit
wheels. Their own small neural network reads them badly (blurry wheels, glare, a camera that sits a bit off).
This agent takes the pictures the cameras already produce, lets two different vision models read the wheels
through an OpenAI-compatible API (default [OpenRouter](https://openrouter.ai)), votes the digits wheel by wheel and only publishes a value that fits
the last one: a counter never goes down and never advances faster than the pipe allows. The result is one
`total_increasing` sensor per meter in Home Assistant (MQTT discovery), usable in the energy dashboard.

```
camera (img_tmp/alg.jpg or raw.jpg)
   -> crop + contrast + 2x enlarge            app/vision.py
   -> model A, model B (OpenRouter)           digits like "3598661", "?" for an unreadable wheel
   -> vote per wheel                          app/plausibility.py
   -> plausibility against the last value     monotonic, max rate, unreadable wheels filled from the last value
   -> MQTT: value, attributes, discovery      app/mqtt_ha.py  -> Home Assistant
```

## Does it read better than the camera? (measured 2026-11-21)

Seven pictures (five gas, two water) taken from the real cameras, the digits checked by eye. "Wheels right" counts
the whole-number wheels, which do not move within minutes; the fraction wheels turn and are judged by the
plausibility check instead.

| Reader                               | Gas, whole wheels | Water, whole wheels | Pictures fully right |
|--------------------------------------|------------------:|--------------------:|---------------------:|
| Camera's own network                 |            55 %   |               50 %  |               0 of 7 |
| `openai/gpt-4o-mini`                 |           100 %   |              100 %  |               7 of 7 |
| `qwen/qwen3-vl-30b-a3b-instruct`     |           100 %   |              100 %  |               7 of 7 |
| `anthropic/claude-haiku-5.5`         |           100 %   |              100 %  |               7 of 7 |
| `google/gemini-2.5-flash-lite`       |           100 %   |              100 %  |   5 of 7 (2 refused) |

The camera answered 1508.633 and 3508.600 for a gas meter that stood at 3598.661, and `1N0.NN` for a water meter at
150.211. The models agree with each other and with the picture. On the fraction wheels (the fastest, red ones) the
models differ by up to 0.03 m³ between two readings, which the vote and the monotonic check absorb. A cheap model
sometimes returns the wrong number of characters; the parser rejects such an answer instead of guessing.
Cost: about 0.0005 USD per call, 192 calls a day at the default interval, roughly 0.10 USD a day.

Run the comparison yourself (pictures from `/img_tmp/alg.jpg`, the camera's own answer from `/json`):

```bash
LLM_API_KEY=... uv run python -m app.evaluate --dir eval --truth gas=3598,wasser=0015 \
    --models openai/gpt-4o-mini,qwen/qwen3-vl-30b-a3b-instruct
```

## Quick start (docker compose)

```bash
git clone https://github.com/DominikLudwig1995/zaehler-agent && cd zaehler-agent
docker compose up -d        # web UI: http://localhost:8000
```

Then do the setup in the UI, nothing to edit by hand:

1. **Settings**: API key (any OpenAI-compatible vision API: OpenRouter, OpenAI, a local Ollama/vLLM via the base URL),
   the models, check interval, daily budget, and the MQTT broker of your Home Assistant.
2. **Meters, Add meter**: the camera's picture URL, number of wheels, rise limit. Press *Load picture*, draw a
   rectangle around the digit row, *Preview what the models see*, *Test read*, *Save*. The sensor shows up in
   Home Assistant by itself (MQTT discovery).

Works with any camera that serves a picture by URL (ESP32-CAM with AI-on-the-edge, IP camera snapshot, Frigate ...).
`docker compose --profile mqtt up -d` adds a local Mosquitto if you have no broker.

Changes are stored in the `zaehler-data` volume (`settings.json`, mode 600, includes the key if you typed it in the
UI) and win over the file and the environment. *Reset* goes back, *Download as config.yml* exports the setup without
secrets. `READ_ONLY=true` turns every change off. The UI has no login of its own: put it behind your reverse proxy's
authentication when it is reachable by others.

## Configuration as a file (optional)

For setups that live in git: `config/config.yml` (see [config.example.yml](config/config.example.yml), every key
explained). Secrets are never in the file: it names the variable (`api_key_env`, `password_env`). Environment
variables override the file; what you saved in the UI overrides both.

| Variable | Default | |
|----------|---------|-|
| `CONFIG_FILE` | `config/config.yml` | |
| `LLM_API_KEY` | | key of the vision API; empty for a local model |
| `LLM_BASE_URL` | `https://openrouter.ai/api/v1` | any OpenAI-compatible endpoint |
| `MODELS` | `openai/gpt-4o-mini,qwen/qwen3-vl-30b-a3b-instruct` | one call per model and reading, digits are voted |
| `INTERVAL_SECONDS` | `1800` | an unchanged picture is skipped |
| `MAX_DAILY_COST_USD` | `0.30` | when spent, no model is called until midnight UTC (survives restarts) |
| `MQTT_HOST/PORT/USER/PASSWORD` | | without host nothing is published |
| `TOPIC_PREFIX`, `DISCOVERY_PREFIX` | `zaehler-agent`, `homeassistant` | |
| `DATA_DIR`, `HISTORY_DAYS` | `/data` in the image, `30` | SQLite history and `settings.json`; empty = memory only |
| `READ_ONLY` | | `true` disables every change |

Per meter: `name`, `title`, `kind` (gas, water, electricity, heat, generic: sets unit and Home Assistant class),
`image_url` (+ `image_headers`), `integer_digits`, `decimals`, `crop`, `rotate`, `mirror`, `max_rate_per_hour`,
`initial_value`, `device_json_url`.

Home Assistant gets one `total_increasing` sensor per meter. Attributes show the decision (`accepted`, `unchanged`,
`rejected`), the digits each model read, the camera's own reading and the cost of the day. The last values are
retained MQTT messages, so a restart continues where it stopped. Wrong start value? `POST /api/meters/{name}/value`
or the *Set value by hand* button.

## UI, API, metrics

| | |
|-|-|
| `GET /` | web UI: value, decision, the camera picture and the crop the models saw, history chart, "Read now" |
| `GET /status`, `/api/config`, `/api/history/{name}`, `/api/image/{name}?crop=` | JSON and pictures |
| `POST /poll/{name}` | read one meter now |
| `GET/PUT /api/settings`, `DELETE /api/settings`, `GET /api/settings/export` | the settings the UI edits |
| `POST /api/meters`, `PUT/DELETE /api/meters/{name}`, `POST /api/meters/test`, `GET /api/probe` | meters: add, change, remove, try, camera preview |
| `POST /api/meters/{name}/value` | set the counter by hand: `{"value": 3600.34}` (start value, replaced counter) |
| `GET /healthz` | liveness |
| `GET /metrics` | Prometheus: `zaehler_value`, `zaehler_readings_total{status}`, `zaehler_last_accepted_timestamp_seconds`, `zaehler_model_errors_total`, `zaehler_camera_errors_total`, `zaehler_cost_usd_today`, `zaehler_budget_exhausted`, `zaehler_agreement` |

Suggested alerts (Prometheus): no accepted value for 6 h, readings only `rejected`, camera or model errors,
budget exhausted, agent down.

## Develop and release

```bash
uv sync && uv run pytest && uv run ruff check . && uv run ruff format --check .
CONFIG_FILE=config/config.yml LLM_API_KEY=... uv run uvicorn app.main:app --port 8000
```

CI (GitHub Actions and Woodpecker): lint, tests with coverage, `pip-audit`; GitHub also runs a `docker compose`
smoke test and Trivy. A tag `vX.Y.Z` builds the image (amd64, arm64) to `ghcr.io`, and creates the GitHub release with
the notes from [CHANGELOG.md](CHANGELOG.md). The Woodpecker pipeline additionally deploys to Nomad
(`deploy/nomad.hcl`, secrets from Vault).

## What it does not do

It does not fix a bad picture. A smeared lens, glare or a camera that cuts off the last wheel still costs
accuracy: the agent then reports `rejected` or keeps the last value instead of publishing a guess. Fix the camera,
then check `/status`.

