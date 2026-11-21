"""Home Assistant over MQTT: discovery messages, the values, and the restore of the last value after a restart."""

from __future__ import annotations

import json
import threading
import time
from typing import Protocol

import paho.mqtt.client as mqtt

from app.config import Meter, Settings


class Publisher(Protocol):
    def publish(self, topic: str, payload: str, retain: bool = True) -> None: ...

    def retained(self, topic: str, timeout: float = 3.0) -> str | None: ...

    def close(self) -> None: ...


class MqttPublisher:
    """Thin paho wrapper: one connection with a last-will, publishes are retained."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="zaehler-agent")
        if settings.mqtt_user:
            self.client.username_pw_set(settings.mqtt_user, settings.mqtt_password)
        self.status_topic = f"{settings.topic_prefix}/status"
        self.client.will_set(self.status_topic, "offline", retain=True)
        self._inbox: dict[str, str] = {}
        self._events: dict[str, threading.Event] = {}
        self.client.on_message = self._on_message

    def connect(self) -> None:
        self.client.connect(self.settings.mqtt_host, self.settings.mqtt_port, keepalive=60)
        self.client.loop_start()
        self.publish(self.status_topic, "online")

    def close(self) -> None:
        self.publish(self.status_topic, "offline")
        self.client.loop_stop()
        self.client.disconnect()

    def publish(self, topic: str, payload: str, retain: bool = True) -> None:
        self.client.publish(topic, payload, qos=1, retain=retain)

    def _on_message(self, _client, _userdata, msg) -> None:
        self._inbox[msg.topic] = msg.payload.decode(errors="replace")
        if ev := self._events.get(msg.topic):
            ev.set()

    def retained(self, topic: str, timeout: float = 3.0) -> str | None:
        ev = self._events.setdefault(topic, threading.Event())
        self.client.subscribe(topic, qos=1)
        ev.wait(timeout)
        self.client.unsubscribe(topic)
        return self._inbox.get(topic)


def state_topic(settings: Settings, meter: Meter) -> str:
    return f"{settings.topic_prefix}/{meter.name}/state"


def attributes_topic(settings: Settings, meter: Meter) -> str:
    return f"{settings.topic_prefix}/{meter.name}/attributes"


def discovery_messages(settings: Settings) -> list[tuple[str, str]]:
    """(topic, payload) for every meter: one total_increasing sensor that works in the energy dashboard."""
    out = []
    for m in settings.meters:
        uid = f"zaehler_agent_{m.name}"
        payload = {
            "name": m.title,
            "unique_id": uid,
            "object_id": uid,
            "device_class": m.device_class,
            "state_class": "total_increasing",
            "unit_of_measurement": m.unit,
            "suggested_display_precision": m.decimals,
            "state_topic": state_topic(settings, m),
            "json_attributes_topic": attributes_topic(settings, m),
            "availability_topic": f"{settings.topic_prefix}/status",
            "device": {
                "identifiers": ["zaehler_agent"],
                "name": "Zähler-Agent",
                "manufacturer": "zaehler-agent",
                "model": "Vision reader for AI-on-the-edge cameras",
            },
        }
        out.append((f"{settings.discovery_prefix}/sensor/{uid}/config", json.dumps(payload)))
    return out


def publish_discovery(pub: Publisher, settings: Settings) -> None:
    for topic, payload in discovery_messages(settings):
        pub.publish(topic, payload)


def publish_reading(
    pub: Publisher, settings: Settings, meter: Meter, value: float | None, attributes: dict
) -> None:
    if value is not None:
        pub.publish(state_topic(settings, meter), f"{value:.{meter.decimals}f}")
    attributes = {**attributes, "updated": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    pub.publish(attributes_topic(settings, meter), json.dumps(attributes))
