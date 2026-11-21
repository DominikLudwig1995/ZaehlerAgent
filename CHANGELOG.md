# Changelog

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
