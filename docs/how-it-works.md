# How it works

```
camera picture (any URL)
   -> orient, crop the digit row, stretch contrast, enlarge 2x     app/vision.py
   -> every model reads the digits ("?" for an unreadable wheel)   app/vision.py
   -> vote per wheel                                               app/plausibility.py
   -> plausibility check against the last accepted value           app/plausibility.py
   -> store (SQLite) and publish (MQTT, Home Assistant, metrics)   app/service.py, app/mqtt_ha.py
```

## 1. The picture

Each round the agent downloads one picture per meter from `image_url`. If the picture is byte-identical to the last
one it is skipped (the camera has not taken a new one). Otherwise it is mirrored and rotated if configured, cropped
to the digit row (`crop`), contrast-stretched and enlarged. The result is exactly what the models see; the meter form
shows it as *Preview what the models see*.

## 2. The models

Every configured model gets the same picture and a short prompt: how many wheels there are, which are whole-number
and which are fraction wheels, and to answer `?` instead of guessing. The answer is one line of JSON
(`{"digits": "0015033?", "confidence": 0.9}`). An answer with the wrong number of characters is rejected, never
repaired. Different models make different mistakes, which is what makes the vote work. Calls run in parallel.

Any OpenAI-compatible chat API with picture input works: OpenRouter (default), OpenAI, Ollama, vLLM. Cost is about
0.0005 USD per call with small models, roughly 0.10 USD per meter and day at the default interval.

## 3. The vote

For every wheel position the digits the models read are counted; `?` does not vote.

- A clear majority wins.
- A tie becomes `?`, and the digits that tied are remembered as the only candidates for that wheel.
- The agreement (share of wheels with a majority) is shown in the UI and exported as a metric.

## 4. The plausibility check

A meter only goes up, and only as fast as the pipe allows. Against the last accepted value:

| Situation | Decision |
|---|---|
| Wrong number of wheels | `rejected` |
| First reading ever, all wheels readable | `accepted` |
| First reading with `?` | `rejected` |
| New value above `last + max_rate_per_hour * hours` | `rejected` (rate) |
| New value more than 0.02 below the last | `rejected` (rollback) |
| New value equal to or slightly below the last | `unchanged` |
| Otherwise | `accepted` |

Unreadable wheels (`?`) are filled with the **smallest** digits that make the value fit the allowed window,
preferring the digits the models actually read there. More than four unreadable wheels are rejected. A rejected
reading never changes the published value; the last good one stays.

`max_rate_per_hour` is the most the meter can plausibly advance in an hour, in its unit. Choose it generously (twice
your peak use) but not absurdly: it is the guard rail against a misread that happens to look plausible.

## 5. State and restarts

The last accepted value of every meter is published as a **retained MQTT message**. After a restart the agent
reads it back and continues from there. Without MQTT the history database is used. The daily cost budget is also
restored from the history, so a restart does not reset it.

## What it cannot do

It does not fix a bad picture. A smeared lens, a camera that cuts off the last wheel or heavy glare cost accuracy; the
agent then reports `rejected` and keeps the last value instead of publishing a guess. Fix the camera (see
[troubleshooting](troubleshooting.md)), then check the dashboard.
