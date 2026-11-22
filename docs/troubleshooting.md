# Troubleshooting

Start at the dashboard: every meter shows the last decision, what each model read, and the picture the models saw.
*Meters → your meter → Live picture / Preview what the models see / Test read* reproduce most problems in a minute.

## A reading is `rejected`

| `reason` | Cause and fix |
|---|---|
| `unreadable wheels do not fit the last value` | The models returned `?` on wheels the plausibility check cannot fill. Check the crop and the picture (glare? half-turned wheel?). Often temporary: the next round fixes it. |
| `N wheels, expected M` | A model returned the wrong number of characters, or `integer_digits + decimals` is wrong for your meter. Count the wheels on the meter. |
| `... is more than ... (rate)` | The value jumped more than `max_rate_per_hour` allows. Either a misread, or the rate is set too low for a real peak. |
| `... is below the last value` | A misread, or the counter was replaced. Use *Set value by hand* after a replacement. |
| `first reading has unreadable wheels` | There is no last value yet and a wheel is unreadable. Set a start value (`initial_value` or by hand), or wait for a clean picture. |

The value in Home Assistant never changes on a rejected reading, so a stretch of rejections is annoying but not
harmful. If it lasts, the `ZaehlerReadingsRejected` alert in [API and metrics](api.md#example-alerts) tells you.

## Every reading is wrong in the same wheel

The crop is probably cutting off a wheel or including the label next to the digits. Redraw it on the live picture,
check *Preview what the models see*, and use *Test read*. If the camera's aligned picture cuts off the last wheel,
use the raw picture (AI-on-the-edge: `raw.jpg` instead of `alg.jpg`).

## "Camera not reachable"

The **agent** must reach the camera, not your browser. From inside the container:
`docker compose exec zaehler-agent python -c "import urllib.request as u; print(len(u.urlopen('http://CAMERA/...').read()))"`.
Check VLANs and firewalls between the container host and the camera. Some cameras serve only one request at a time;
the agent never reads a camera in parallel.

## The models return nothing or errors

- Check the API key in *Settings* and the credit of your provider.
- Check the model names. OpenRouter uses `vendor/model`; Ollama uses its own names and the base URL
  `http://host:11434/v1`.
- A model without picture support answers with text. Use *Test read* to see which model fails.
- `zaehler_model_errors_total{model}` counts failures per model.

## It costs too much

`max_daily_cost_usd` stops all calls for the rest of the UTC day. To cut cost: use fewer or cheaper models, raise
`interval_seconds`, or run a local model through Ollama. The cost bar at the top of the dashboard shows today.

## No sensor in Home Assistant

- MQTT host, user and password in *Settings*; the dashboard shows `MQTT on` when a host is set.
- The broker user needs write access to `zaehler-agent/#` and `homeassistant/#`.
- Home Assistant must use the same discovery prefix (`homeassistant` by default).
- Watch the broker: `mosquitto_sub -h BROKER -t 'homeassistant/sensor/zaehler_agent_+/config' -v`.

## Home Assistant shows a wrong or old start value

The agent restores the last value from the retained MQTT message. To correct it, use *Set value by hand* in the
dashboard (or `POST /api/meters/{name}/value`).

## The UI lost my changes after a restart

There is no persistent `DATA_DIR`. With docker compose the named volume handles this; with other runtimes mount a
volume on `/data`. See [deployment](deployment.md#persistence).

## Still stuck?

Open an issue with the dashboard's *Preview what the models see* picture (blur anything private), the meter settings
without secrets (*Download as config.yml*) and the agent log.
