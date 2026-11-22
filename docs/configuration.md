# Configuration

There are three layers. Later ones win:

1. **Config file** (`config/config.yml`, optional): good for setups that live in git. Start from
   [`config/config.example.yml`](../config/config.example.yml).
2. **Environment variables**: what docker-compose and orchestrators use.
3. **Web UI**: everything you change in the browser is stored in `DATA_DIR/settings.json` (mode 600) and wins over
   the other two, so what you click is what runs after a restart. *Reset to file / environment* in Settings deletes
   it. *Download as config.yml* exports the current setup **without secrets**.

Without a config file the agent starts empty and you do everything in the UI.

## General settings

| Setting | Environment | Default | |
|---|---|---|---|
| `interval_seconds` | `INTERVAL_SECONDS` | `1800` | How often every meter is read. An unchanged picture is skipped. Minimum 60. |
| `max_daily_cost_usd` | `MAX_DAILY_COST_USD` | `0.30` | When spent, no model is called until midnight UTC. Survives restarts. |
| `vision.base_url` | `LLM_BASE_URL` | `https://openrouter.ai/api/v1` | Any OpenAI-compatible endpoint. |
| `vision.api_key_env` | `LLM_API_KEY` | | Name of the variable that holds the key (file) / the key itself (environment); empty is fine for a local model. `OPENROUTER_API_KEY` is accepted as a fallback. |
| `vision.models` | `MODELS` | two small models | One call per model and reading; the digits are voted. Use different models. Comma separated in the environment. |
| `mqtt.host` / `port` / `user` | `MQTT_HOST` / `MQTT_PORT` / `MQTT_USER` | | Without a host nothing is published (UI and metrics only). |
| `mqtt.password_env` | `MQTT_PASSWORD` | | |
| `mqtt.topic_prefix` | `TOPIC_PREFIX` | `zaehler-agent` | |
| `mqtt.discovery_prefix` | `DISCOVERY_PREFIX` | `homeassistant` | |
| `data_dir` | `DATA_DIR` | `/data` in the image | SQLite history and `settings.json`. Empty means memory only. |
| `history_days` | `HISTORY_DAYS` | `30` | |
| | `CONFIG_FILE` | `config/config.yml` | |
| | `READ_ONLY` | | `true` disables every change in the UI and API. |

Secrets are never read from the config file itself: it names the variable that holds them (`api_key_env`,
`password_env`).

## Meters

One meter is one camera looking at one counter.

| Setting | Default | |
|---|---|---|
| `name` | | Short id for URLs, topics and metrics: lowercase letters, digits, `-` and `_`. |
| `title` | | Shown in the UI and in Home Assistant. |
| `kind` | `generic` | `gas`, `water`, `electricity`, `heat`, `generic`. Sets the unit and the Home Assistant device class. |
| `image_url` | | A picture of the counter (HTTP GET). Any camera or snapshot URL. |
| `image_headers` | | For example `{Authorization: "Bearer ${CAM_TOKEN}"}`; `${VAR}` is expanded from the environment. |
| `integer_digits` | | Wheels left of the decimal point. |
| `decimals` | | Wheels right of it (usually the red ones). |
| `crop` | whole picture | `[x0, y0, x1, y1]` of the digit row, in the picture after `rotate` and `mirror`. Draw it in the UI. |
| `rotate` | `0` | Degrees counter-clockwise, applied before the crop. |
| `mirror` | `false` | Mirror horizontally, applied before the crop. |
| `max_rate_per_hour` | `10` | The most the counter can plausibly advance in an hour, in its unit. See [how it works](how-it-works.md#4-the-plausibility-check). |
| `initial_value` | | Start value until one is stored. Optional. |
| `unit`, `device_class` | by `kind` | Override the defaults. |
| `device_json_url` | | AI-on-the-edge `/json`: the camera's own reading is shown next to the models' for comparison. |
| `live_url` | `image_url` | A fresh picture on demand (AI-on-the-edge: `/capture`). |
| `light_on_url`, `light_off_url` | | Called before and after the live picture (`/lighton`, `/lightoff`). |
| `light_settle_seconds` | `2` | Wait after the light went on. |

### AI-on-the-edge cameras

The *Fill for AI-on-the-edge* button in the meter form sets the usual URLs from the camera's IP:

| Setting | URL |
|---|---|
| `image_url` | `http://IP/img_tmp/raw.jpg` (or `alg.jpg`, the picture the camera has already aligned) |
| `device_json_url` | `http://IP/json` |
| `live_url` | `http://IP/capture` (`/capture_with_flashlight` switches the light on for one shot) |
| `light_on_url` / `light_off_url` | `http://IP/lighton` / `http://IP/lightoff` |

Use `raw.jpg` when the aligned picture cuts off the last wheel.

### Finding `max_rate_per_hour`

Look at the highest hourly use you have seen, double it, and round up. For a household water meter 1.5 m³/h is
plenty, for a gas meter of a family house 4 m³/h. A value that is too low rejects real peaks; one that is too high
lets a misread through.

## Example

```yaml
interval_seconds: 1800
max_daily_cost_usd: 0.30
vision:
  base_url: https://openrouter.ai/api/v1
  api_key_env: LLM_API_KEY
  models: [openai/gpt-4o-mini, qwen/qwen3-vl-30b-a3b-instruct]
mqtt:
  host: 192.168.1.10
  user: zaehler
  password_env: MQTT_PASSWORD
meters:
  - name: water
    title: Water meter
    kind: water
    image_url: http://192.168.1.51/img_tmp/raw.jpg
    integer_digits: 5
    decimals: 3
    crop: [60, 0, 640, 200]
    max_rate_per_hour: 1.5
```
