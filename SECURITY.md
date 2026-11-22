# Security policy

## Supported versions

Only the latest release receives fixes.

## Reporting a vulnerability

Please **do not open a public issue**. Use GitHub's private vulnerability reporting
(*Security → Report a vulnerability* on this repository). You get an answer within a week. Fixes are released
as a patch version with a note in the [changelog](CHANGELOG.md).

## Threat model, in short

- The web UI and API have **no authentication**. They can change settings, trigger paid model calls, switch a
  camera's light and set the published meter value. Run the agent on a trusted network or behind a reverse proxy
  with authentication, and use `READ_ONLY=true` for shared dashboards. See
  [docs/deployment.md](docs/deployment.md#access-control).
- API keys and the MQTT password are never sent to the browser. A key you type into the UI is stored in
  `DATA_DIR/settings.json` (mode 600) inside the data volume. Prefer environment variables or a secrets manager if
  that does not fit your setup.
- The agent fetches the picture URLs you configure and, through `/api/probe`, any `http(s)` URL you give it. That is
  how the meter form shows a camera. Do not expose the UI to people you do not trust.
- The container runs as a non-root user. Images are scanned with Trivy in CI.
