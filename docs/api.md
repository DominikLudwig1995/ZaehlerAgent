# API and metrics

The web UI is a thin client of this API. Everything it does you can script. Endpoints that change something answer
`403` when `READ_ONLY=true`. There is no authentication, see [access control](deployment.md#access-control).

## Read

| Endpoint | |
|---|---|
| `GET /healthz` | Liveness: `{"status": "ok"}` |
| `GET /status` | Per meter: value, time, decision (`status`, `reason`), voted `digits`, each model's `samples`, `agreement`, camera reading, cost today |
| `GET /api/config` | Models, interval, budget, MQTT on/off, meters, `read_only` |
| `GET /api/history/{name}?hours=72&limit=50` | `series` (the published values, for charts) and the latest `readings` |
| `GET /api/image/{name}?crop=true` | The last picture from the camera; with `crop=true` what the models saw |
| `GET /api/live/{name}?light=true` | A fresh picture now; with `light=true` the camera's light is switched on for the shot (needs write access) |
| `GET /api/settings` | All editable settings, secrets reported only as `llm_api_key_set` / `mqtt_password_set` |
| `GET /api/settings/export` | The current setup as `config.yml`, without secrets |
| `GET /metrics` | Prometheus text format |

## Change

| Endpoint | |
|---|---|
| `POST /poll/{name}` | Read one meter now, also when the picture did not change |
| `POST /api/meters/{name}/value` | Set the counter by hand: `{"value": 3600.34}` (start value, replaced counter) |
| `PUT /api/settings` | Change general settings. Only the keys you send change. `{"models": "a/b, c/d", "interval_seconds": 600}`. An empty `llm_api_key` or `mqtt_password` means keep. |
| `DELETE /api/settings` | Forget everything edited in the UI, back to the file and the environment |
| `POST /api/meters` | Add a meter (body: the meter settings, see [configuration](configuration.md#meters)) |
| `PUT /api/meters/{name}` | Change a meter. Only the keys you send change. |
| `DELETE /api/meters/{name}` | Remove a meter; its Home Assistant sensor is removed too |
| `POST /api/meters/test` | Try a meter definition without saving: downloads the picture, reads it with every model, returns the vote and the cost |
| `GET /api/probe?url=...&rotate=&mirror=&crop=` | A camera picture as the agent would see it: oriented (to draw the crop) or, with `crop`, as the models get it |

Errors use the usual HTTP codes with `{"detail": "..."}`: `404` unknown meter, `409` meter exists, `422` invalid
setting, `502` camera not reachable, `403` read-only.

```bash
curl -s localhost:8000/status | jq
curl -s -X POST localhost:8000/poll/water
curl -s -X POST -H 'Content-Type: application/json' -d '{"value": 150.331}' localhost:8000/api/meters/water/value
```

## Prometheus metrics

| Metric | Type | |
|---|---|---|
| `zaehler_up` | gauge | 1 while the agent runs |
| `zaehler_uptime_seconds` | gauge | |
| `zaehler_value{meter}` | gauge | Last accepted counter value |
| `zaehler_readings_total{meter,status}` | counter | Readings by decision: `accepted`, `unchanged`, `rejected`, `error` |
| `zaehler_last_poll_timestamp_seconds{meter}` | gauge | Last reading that reached a decision |
| `zaehler_last_accepted_timestamp_seconds{meter}` | gauge | Last *changed* value |
| `zaehler_agreement{meter}` | gauge | Share of wheels the models agreed on in the last reading |
| `zaehler_model_errors_total{model}` | counter | Failed model calls |
| `zaehler_camera_errors_total{meter}` | counter | Failed picture downloads |
| `zaehler_cost_usd_today` | gauge | Model cost of the current UTC day |
| `zaehler_budget_exhausted` | gauge | 1 when the daily budget is spent and no model is called |
| `zaehler_mqtt_connected` | gauge | 1 when MQTT is configured |

### Example alerts

```yaml
groups:
  - name: zaehler-agent
    rules:
      - alert: ZaehlerAgentDown
        expr: absent(zaehler_up == 1)
        for: 10m
      - alert: ZaehlerNoNewValue
        # water and gas are used every day: no change for 6 hours means a bad picture or a blind camera
        expr: time() - zaehler_last_accepted_timestamp_seconds > 6 * 3600
        for: 15m
      - alert: ZaehlerReadingsRejected
        expr: >
          increase(zaehler_readings_total{status="rejected"}[3h]) >= 4
          and increase(zaehler_readings_total{status="accepted"}[3h]) == 0
      - alert: ZaehlerCameraUnreachable
        expr: increase(zaehler_camera_errors_total[30m]) > 0
        for: 30m
      - alert: ZaehlerModelErrors
        expr: increase(zaehler_model_errors_total[1h]) > 3
      - alert: ZaehlerBudgetExhausted
        expr: zaehler_budget_exhausted == 1
        for: 5m
```

Tune `ZaehlerNoNewValue` to your use: a holiday home or a summer gas meter legitimately stands still for days.
