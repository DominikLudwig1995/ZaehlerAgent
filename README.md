# zaehler-agent

Reads the gas and the water meter with a vision model and reports the values to Home Assistant.

Two ESP32 cameras ([AI-on-the-edge-device](https://github.com/jomjol/AI-on-the-edge-device)) look at the digit
wheels. Their own small neural network reads them badly (blurry wheels, glare, a camera that sits a bit off).
This agent takes the pictures the cameras already produce, lets two different vision models read the wheels
through [OpenRouter](https://openrouter.ai), votes the digits wheel by wheel and only publishes a value that fits
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
OPENROUTER_API_KEY=... uv run python -m app.evaluate --dir eval --truth gas=3598,wasser=0015 \
    --models openai/gpt-4o-mini,qwen/qwen3-vl-30b-a3b-instruct
```

## Configuration

`config/meters.yml` describes the meters (camera URLs, number of wheels, crop of the digit row, the highest
plausible rate in m³/h, a known start value). Everything else is environment:

| Variable             | Default                                                  | |
|----------------------|----------------------------------------------------------|-|
| `OPENROUTER_API_KEY` |                                                          | required |
| `MODELS`             | `openai/gpt-4o-mini,qwen/qwen3-vl-30b-a3b-instruct`      | one call per model and reading, the digits are voted |
| `INTERVAL_SECONDS`   | `1800`                                                   | a picture that did not change is skipped |
| `MAX_DAILY_COST_USD` | `0.30`                                                   | when spent, the agent stops calling the model until midnight |
| `MQTT_HOST/PORT/USER/PASSWORD` |                                                | without `MQTT_HOST` nothing is published (status page only) |
| `TOPIC_PREFIX`       | `zaehler-agent`                                          | |
| `DISCOVERY_PREFIX`   | `homeassistant`                                          | |
| `METERS_FILE`        | `config/meters.yml`                                      | |

Home Assistant gets one sensor per meter (`sensor.zaehler_agent_gas`, `sensor.zaehler_agent_wasser`, `device_class` gas / water,
`state_class` total_increasing). Attributes show the last decision (`accepted`, `unchanged`, `rejected`), the digits
each model read, the camera's own reading and the cost of the day, so a wrong value can be traced. The last values are
retained MQTT messages: a restart picks up where it stopped.

`GET /healthz` (liveness), `GET /status` (all meters), `POST /poll/{name}` (read one meter now).

## Run and deploy

```bash
uv sync && uv run pytest && uv run ruff check . && uv run ruff format --check .
OPENROUTER_API_KEY=... MQTT_HOST=... uv run uvicorn app.main:app --port 8000
```

The Woodpecker pipeline (`.woodpecker.yml`) tests, builds the image with Kaniko, pushes it to Harbor and rolls it
out to Nomad with `deploy/nomad-deploy.sh deploy/nomad.hcl <image>` (a failed deployment reverts itself). The job
reads its secrets from Vault (`secret/nomad/zaehler-agent`: `openrouter_api_key`, `mqtt_user`, `mqtt_password`).

The cameras sit in a separate network. The Nomad nodes need HTTP access to them (port 80); the container is NATed
to the node address.

## What it does not do

It does not fix a bad picture. A smeared lens, glare or a camera that cuts off the last wheel still costs
accuracy: the agent then reports `rejected` or keeps the last value instead of publishing a guess. Fix the camera,
then check `/status`.

Created from `app-template`; template updates arrive with `uvx copier update`.
