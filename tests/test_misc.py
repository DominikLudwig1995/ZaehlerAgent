import json
from unittest.mock import MagicMock, patch

from app.config import Settings
from app.evaluate import device_digits, score
from app.mqtt_ha import MqttPublisher


def test_settings_from_env(tmp_path):
    f = tmp_path / "m.yml"
    f.write_text(
        "meters:\n  - {name: a, title: A, kind: gas, image_url: http://x/a.jpg, integer_digits: 4,"
        " decimals: 3, crop: [0, 0, 10, 10], max_rate_per_hour: 2.0}\n"
    )
    s = Settings.from_env(
        {
            "METERS_FILE": str(f),
            "MODELS": "a/b, c/d",
            "INTERVAL_SECONDS": "60",
            "MQTT_HOST": "mq",
            "MAX_DAILY_COST_USD": "0.1",
        }
    )
    assert s.models == ("a/b", "c/d") and s.interval_seconds == 60 and s.mqtt_host == "mq"
    assert s.max_daily_cost_usd == 0.1 and s.meters[0].digits == 7
    assert Settings.from_env({"METERS_FILE": str(tmp_path / "missing.yml")}).meters == ()


def test_evaluate_helpers(tmp_path, gas):
    img = tmp_path / "gas-1.jpg"
    img.write_bytes(b"x")
    assert device_digits(img, gas) == ""  # no json next to it
    img.with_suffix(".json").write_text(json.dumps({"main": {"raw": "1N0.5N3"}}))
    assert device_digits(img, gas) == "01?05?3"
    assert score("3598661", "3598") == (4, 4)
    assert score("1508633", "3598") == (2, 4)


def test_mqtt_publisher_publishes_retained_and_restores(settings):
    s = Settings(mqtt_host="mq", mqtt_user="u", mqtt_password="p", meters=settings.meters)
    with patch("app.mqtt_ha.mqtt.Client") as client_cls:
        client = client_cls.return_value
        pub = MqttPublisher(s)
        pub.connect()
        client.username_pw_set.assert_called_with("u", "p")
        client.will_set.assert_called_with("zaehler-agent/status", "offline", retain=True)
        client.connect.assert_called_with("mq", 1883, keepalive=60)
        pub.publish("t", "v")
        client.publish.assert_called_with("t", "v", qos=1, retain=True)
        # a retained message that arrives while we wait is returned
        msg = MagicMock(topic="zaehler-agent/gas/state", payload=b"3598.661")
        client.subscribe.side_effect = lambda *a, **k: pub._on_message(None, None, msg)
        assert pub.retained("zaehler-agent/gas/state", timeout=0.1) == "3598.661"
        pub.close()
        client.disconnect.assert_called()
