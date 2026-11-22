# Home Assistant

ZaehlerAgent talks to Home Assistant over **MQTT discovery**. There is no custom integration to install: point the
agent at the same MQTT broker as Home Assistant and the sensors appear on their own.

## Requirements

- An MQTT broker (for example Mosquitto) and the MQTT integration in Home Assistant.
- A broker user for the agent that may publish and subscribe below `zaehler-agent/#` (the topic prefix) and publish
  to `homeassistant/sensor/zaehler_agent_*/config`.

## What you get

One device **ZaehlerAgent** with one sensor per meter:

| | |
|---|---|
| State | The last accepted meter reading, for example `150.331` |
| `device_class` | `gas`, `water` or `energy` (by `kind`; none for `generic`) |
| `state_class` | `total_increasing` |
| Unit | `m³`, `kWh` or what you set |

The entity id is built from the device and meter title, for example `sensor.zaehleragent_water_meter`. It is
kept when you later rename the meter, because the sensor's unique id (`zaehler_agent_<name>`) does not change.

### Attributes

Every sensor carries the last decision, so a wrong value can always be traced:

| Attribute | Meaning |
|---|---|
| `status` | `accepted`, `unchanged`, `rejected` or `error` |
| `reason` | Why a reading was rejected or what happened |
| `digits` | The voted digits, `?` for an unreadable wheel |
| `samples`, `models` | The digits each model read, and which models |
| `agreement`, `confidence` | Share of wheels with a majority; the models' own confidence |
| `device_reading` | The camera's own reading, when `device_json_url` is set |
| `cost_today_usd` | Model cost of the current day |
| `updated` | Time of the last update |

## Energy dashboard

Use the sensors directly as **gas** or **water** source in *Settings → Dashboards → Energy*. They are
`total_increasing` with a proper device class, so they are accepted as they are. Set the price per unit in the
dashboard to get cost.

Statistics are derived from the sensor state. If a camera was blind for days and then caught up, Home Assistant books
the whole difference to the hour it was noticed. You can spread it afterwards with the `recorder.import_statistics`
and `recorder.adjust_sum_statistics` WebSocket calls if it matters to you.

## MQTT topics

| Topic | Content |
|---|---|
| `{prefix}/{name}/state` | The value, retained |
| `{prefix}/{name}/attributes` | JSON with the attributes above, retained |
| `{prefix}/status` | `online` / `offline` (last will), makes the sensors unavailable when the agent is down |
| `{discovery_prefix}/sensor/zaehler_agent_{name}/config` | The discovery message, retained. Deleting a meter publishes an empty payload, which removes the entity. |

`prefix` is `zaehler-agent` and `discovery_prefix` is `homeassistant` by default.

## Replacing the camera's own MQTT

AI-on-the-edge publishes its own sensors. When you switch to this agent:

1. Disable the MQTT section of the camera (comment out `[MQTT]` in `config.ini`) and restart the camera.
2. Clear its retained topics (`<main topic>/#` and `homeassistant/+/<main topic>/#`) with an empty retained
   publish, so Home Assistant drops the old entities.
3. Point dashboards, helpers and the energy configuration at the new sensor.
