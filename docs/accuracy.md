# Accuracy

Does a vision model read better than the camera's own network? Measured on 2026-11-21 with seven pictures (five gas,
two water) taken from real AI-on-the-edge cameras, the digits checked by eye.

"Whole wheels" counts the whole-number wheels, which do not move within minutes. The fraction wheels turn and are
judged by the plausibility check instead.

| Reader | Gas, whole wheels | Water, whole wheels | Pictures fully right |
|---|---:|---:|---:|
| Camera's own network | 55 % | 50 % | 0 of 7 |
| `openai/gpt-4o-mini` | 100 % | 100 % | 7 of 7 |
| `qwen/qwen3-vl-30b-a3b-instruct` | 100 % | 100 % | 7 of 7 |
| `anthropic/claude-haiku-5.5` | 100 % | 100 % | 7 of 7 |
| `google/gemini-2.5-flash-lite` | 100 % | 100 % | 5 of 7 (2 refused) |

The camera answered `1508.633` and `3508.600` for a gas meter that stood at `3598.661`, and `1N0.NN` for a water
meter at `150.211`. The models agree with each other and with the picture.

On the fraction wheels (the fastest, red ones) the models differ by up to 0.03 m³ between two readings. The vote and
the monotonic check absorb that. A cheap model sometimes returns the wrong number of characters; the parser rejects
such an answer instead of guessing.

Cost: about 0.0005 USD per call, 192 calls a day for two meters at the default interval, roughly 0.10 USD a day.

## Run the comparison on your own pictures

Collect pictures and note the true whole-number digits, then:

```bash
LLM_API_KEY=... uv run python -m app.evaluate --dir eval --truth water=0015,gas=3598 \
    --models openai/gpt-4o-mini,qwen/qwen3-vl-30b-a3b-instruct
```

`eval/` holds the pictures as `<meter>-<time>.jpg` (the folder is git-ignored) and, optionally, the camera's own
answer from `/json` as `<meter>-<time>.json`. `--truth` gives the leading whole-number wheels you know to be right.
The meter definitions come from `--meters` (default `config/config.yml`).

Treat the numbers above as a data point, not a guarantee: they come from one household's cameras. Your lighting,
lens and counter will differ, which is why the UI has a *Test read* button.
