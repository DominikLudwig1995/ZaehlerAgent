import time

from app.metrics import Metrics
from app.storage import History


def test_history_roundtrip_and_purge(tmp_path):
    h = History(str(tmp_path), keep_days=1)
    h.add(
        "gas",
        {"status": "accepted", "digits": "1234567", "samples": ["1"], "models": ["m"]},
        123.4,
        0.01,
    )
    h.add("gas", {"status": "rejected", "reason": "x"}, 123.4, 0.02)
    assert [r["status"] for r in h.recent("gas")] == ["rejected", "accepted"]
    assert len(h.recent()) == 2
    assert h.series("gas") and h.series("gas")[0][1] == 123.4
    assert abs(h.cost_since(time.time() - 60) - 0.03) < 1e-9
    h._db.execute("update readings set ts = 0")
    h.purge()
    assert h.recent() == []


def test_metrics_render():
    m = Metrics()
    m.inc("zaehler_readings_total", meter="gas", status="accepted")
    m.set("zaehler_value", 3.5, meter='ga"s')
    out = m.render()
    assert 'zaehler_readings_total{meter="gas",status="accepted"} 1' in out
    assert 'meter="ga\\"s"' in out and "# TYPE zaehler_value gauge" in out


def test_metrics_keep_full_precision():
    m = Metrics()
    m.set("zaehler_last_accepted_timestamp_seconds", 1795335472.25, meter="gas")
    m.set("zaehler_value", 3605.365, meter="gas")
    m.inc("zaehler_readings_total", 2_000_000, meter="gas", status="accepted")
    out = m.render()
    assert 'zaehler_last_accepted_timestamp_seconds{meter="gas"} 1795335472.25' in out
    assert 'zaehler_value{meter="gas"} 3605.365' in out
    assert 'status="accepted"} 2000000' in out
