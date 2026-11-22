# Contributing

Thanks for helping. Bug reports, camera and model experience reports, documentation fixes and code are all welcome.

## Before you open an issue

- Read [troubleshooting](docs/troubleshooting.md): most rejected readings are a crop or a picture problem.
- For a wrong reading, attach the dashboard's *Preview what the models see* picture (blur anything private), the
  meter settings without secrets (*Settings → Download as config.yml*) and the agent log.
- Questions and "does it work with my camera" go to GitHub Discussions or an issue labelled `question`.

## Development

See [docs/development.md](docs/development.md). In short:

```bash
uv sync
uv run python scripts/demo.py        # try the UI without a camera
uv run ruff check . && uv run ruff format --check . && uv run mypy app && uv run pytest
```

## Pull requests

- One topic per pull request, branched from `main`. Keep it small enough to review.
- Add or update tests: the build fails below 90 % coverage, and a new setting needs a test and a line in
  [docs/configuration.md](docs/configuration.md).
- Update the [changelog](CHANGELOG.md) under `Unreleased`. Call out anything that breaks existing setups: API
  endpoints, setting names, the config format, the MQTT topics.
- Commit messages are in English, imperative mood, a short subject line (`Reject readings with the wrong wheel count`)
  and a body that says *why* when it is not obvious.
- No secrets, no real IP addresses or host names of your network, no pictures of your home in commits or tests.
  Use documentation addresses (`192.0.2.x`, `example.com`).

## Design rules

- `plausibility.py` stays a pure function of its inputs. It is the heart of the project and the best tested part.
- The UI is one HTML file with no build step and no dependencies.
- A camera is never read in parallel; many cheap ESP32 cameras serve one request at a time.
- A rejected reading never changes the published value.

## Code of conduct

Be kind and assume good faith. See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
