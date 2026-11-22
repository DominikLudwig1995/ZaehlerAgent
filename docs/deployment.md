# Deployment

## docker compose

```bash
docker compose up -d        # web UI and API on http://localhost:8000
```

The [`docker-compose.yml`](../docker-compose.yml) in the repository runs the published image
(`ghcr.io/dominikludwig1995/zaehleragent`) with a named volume for `/data` and needs no config file. Set everything
up in the UI. Options:

| | |
|---|---|
| `docker compose up -d --build` | Build from source instead of pulling |
| `docker compose --profile mqtt up -d` | Also start a local Mosquitto (no authentication, for trying it out) |
| `.env` file | `LLM_API_KEY=...` and `MQTT_PASSWORD=...` instead of typing them into the UI |
| `READ_ONLY=true` | Show everything, change nothing |
| Config file | Uncomment the `config.yml` volume line to start from a file, see [configuration](configuration.md) |

Pin a version in production (`image: ghcr.io/dominikludwig1995/zaehleragent:2.2.0`) instead of `latest`.

The container runs as a non-root user and has a health check on `/healthz`. The image is built for amd64 and arm64
(Raspberry Pi 4 and newer).

## Access control

The UI has no login. It can change settings, show a stored API key's presence, trigger paid model calls and switch a
camera's light. Treat it like any admin UI:

- Keep it on the LAN, and put a reverse proxy with authentication in front of anything that is reachable by others.
  Traefik with forward auth (tinyauth, Authelia, oauth2-proxy), Caddy with basic auth or nginx with `auth_request`
  all work. The UI uses relative URLs and runs at the root of a host name.
- Or set `READ_ONLY=true` for a shared dashboard: all write endpoints answer `403`, including *Read now*.

The agent never sends your API key to the browser. Settings only report whether a key is set.

## Persistence

`DATA_DIR` (default `/data`) holds `history.db` (readings) and `settings.json` (what you changed in the UI,
including keys you typed in). Mount a volume there. Without one, UI changes live until the next restart.

## Prometheus

`GET /metrics` exposes the agent. Scrape it like any other target:

```yaml
scrape_configs:
  - job_name: zaehler-agent
    static_configs:
      - targets: ['zaehler-agent:8000']
```

Metrics and ready-made alert rules are in [API and metrics](api.md#prometheus-metrics).

## Nomad

[`deploy/nomad.hcl`](../deploy/nomad.hcl) is the job the maintainer runs: one task, the config inline as a template,
secrets from Vault, Traefik labels with forward auth, a Consul health check and `auto_revert`.
[`deploy/nomad-deploy.sh`](../deploy/nomad-deploy.sh) submits it through the HTTP API and waits for the deployment.
Adapt addresses, domain and secret paths; the structure is a good starting point. A CI test parses the inline config
so a typo cannot reach the cluster.

The job keeps `DATA_DIR` in the allocation directory (`/alloc/data`) on a sticky, migrating ephemeral disk. History
and everything changed in the UI survive updates, restarts and a reschedule to another node. A node that is lost for
good takes them along; the config inside the job is the fallback. Once something was saved in the UI,
`settings.json` wins over the config in the job; *Reset to file / environment* in Settings drops it again. For
stronger guarantees mount a host or CSI volume on `/data` instead.

## Upgrading

1. Read the [changelog](../CHANGELOG.md) for breaking changes.
2. `docker compose pull && docker compose up -d`.

Settings and history live in the volume and survive. The agent creates the history database on first start.

## Sizing and cost

The agent needs about 100 MB of memory and almost no CPU. Cost is dominated by the vision calls: with two small
models and one meter read every 30 minutes, roughly 0.10 USD a day. `max_daily_cost_usd` caps it; a local model
(Ollama) makes it free.
