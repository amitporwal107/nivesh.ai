"""Pluggable message bus — produce IngestionCompleted + per-source events.

Two implementations:
    LocalLogBus  — writes events to stdout (JSON line) and to
                   nidp.local_event_log table for replay during dev/CI.
                   Default in dev.
    KafkaBus     — confluent-kafka producer with Avro serializer wired to
                   Confluent Schema Registry. Default in prod.

Selection by env: NIDP_EVENT_BUS ∈ {"local", "kafka"}.

Interface (async — Kafka producer is callback-based, but we expose
async wrapping so the ingester `await`s on flush):

    bus = get_bus()
    await bus.publish(topic, key, value, schema_name=…, schema_version=1)
    await bus.flush()

Schema names map to .avsc files in nidp/contracts/. The bus does the
schema-registry lookup and Avro encode.
"""
from __future__ import annotations

import abc
import asyncio
import json
import logging
import os
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

from nidp.shared.config import NIDP_ROOT
from nidp.shared.metrics import KAFKA_PUBLISH

logger = logging.getLogger(__name__)

CONTRACTS_DIR = NIDP_ROOT / "contracts"


# ── Interface ───────────────────────────────────────────────────────
class EventBus(abc.ABC):
    @abc.abstractmethod
    async def publish(
        self,
        topic: str,
        key: str,
        value: dict,
        *,
        schema_name: Optional[str] = None,
        schema_version: int = 1,
        headers: Optional[dict] = None,
    ) -> None: ...

    @abc.abstractmethod
    async def flush(self, timeout_s: float = 10.0) -> None: ...

    @abc.abstractmethod
    async def close(self) -> None: ...


# ── Local bus (dev / CI) ────────────────────────────────────────────
class LocalLogBus(EventBus):
    """Writes events to stdout (JSON) and optionally to a local file —
    no Kafka required. Useful for unit tests + initial validation
    before the Kafka cluster lands."""

    def __init__(self, log_file: Optional[Path] = None) -> None:
        self.log_file = log_file or (
            Path(os.environ.get("NIDP_LOCAL_BUS_PATH") or "/tmp/nidp_events.jsonl")
        )

    async def publish(
        self,
        topic: str,
        key: str,
        value: dict,
        *,
        schema_name: Optional[str] = None,
        schema_version: int = 1,
        headers: Optional[dict] = None,
    ) -> None:
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "topic": topic,
            "key": key,
            "schema": schema_name,
            "version": schema_version,
            "headers": headers or {},
            "value": value,
        }
        line = json.dumps(record, default=_json_default, separators=(",", ":"))
        try:
            with self.log_file.open("a") as fp:
                fp.write(line + "\n")
            KAFKA_PUBLISH.labels(topic=topic, status="ok").inc()
        except Exception as e:                                     # noqa: BLE001
            logger.warning("LocalLogBus write failed: %s", e)
            KAFKA_PUBLISH.labels(topic=topic, status="error").inc()

    async def flush(self, timeout_s: float = 10.0) -> None:
        return None

    async def close(self) -> None:
        return None


# ── Kafka bus (prod) ────────────────────────────────────────────────
class KafkaBus(EventBus):
    """Confluent Kafka producer with Avro + Schema Registry.

    Lazy-imports confluent_kafka so dev environments without it still
    boot. Schema files live in nidp/contracts/<schema_name>.avsc.
    """

    def __init__(
        self,
        brokers: Optional[str] = None,
        schema_registry_url: Optional[str] = None,
    ) -> None:
        self.brokers = brokers or os.environ.get("NIDP_KAFKA_BROKERS", "localhost:9092")
        self.schema_registry_url = (
            schema_registry_url
            or os.environ.get("NIDP_SCHEMA_REGISTRY_URL", "http://localhost:8081")
        )
        try:
            from confluent_kafka import Producer                   # type: ignore[import-not-found]
            from confluent_kafka.schema_registry import (          # type: ignore[import-not-found]
                SchemaRegistryClient,
            )
            from confluent_kafka.schema_registry.avro import (     # type: ignore[import-not-found]
                AvroSerializer,
            )
            from confluent_kafka.serialization import (            # type: ignore[import-not-found]
                MessageField, SerializationContext, StringSerializer,
            )
        except ImportError as e:                                   # pragma: no cover
            raise RuntimeError(
                "Kafka bus requires confluent-kafka[avro,schema-registry]."
            ) from e
        self._Producer = Producer
        self._AvroSerializer = AvroSerializer
        self._StringSerializer = StringSerializer
        self._SerializationContext = SerializationContext
        self._MessageField = MessageField

        self._sr = SchemaRegistryClient({"url": self.schema_registry_url})
        self._producer = Producer({
            "bootstrap.servers": self.brokers,
            "enable.idempotence": True,
            "acks": "all",
            "compression.type": "lz4",
            "linger.ms": 10,
            "client.id": os.environ.get("NIDP_KAFKA_CLIENT_ID", "nidp-producer"),
        })
        self._key_ser = StringSerializer("utf_8")
        self._serializers: dict[str, Any] = {}
        # Delivery errors collected via on_delivery; surfaced at flush().
        # We do NOT block per-publish on the delivery future because
        # confluent-kafka's callbacks only fire when poll() is called
        # from Python, and a single poll(0) before await deadlocks the
        # event loop until librdkafka decides to retry — which on a
        # slow broker can be longer than a Cloud Run job timeout.
        self._delivery_errors: list[str] = []

    def _get_serializer(self, schema_name: str):
        if schema_name in self._serializers:
            return self._serializers[schema_name]
        schema_path = CONTRACTS_DIR / f"{schema_name}.avsc"
        if not schema_path.exists():
            raise FileNotFoundError(
                f"Avro schema not found: {schema_path} "
                f"(schema_name={schema_name!r})"
            )
        schema_str = schema_path.read_text()
        ser = self._AvroSerializer(self._sr, schema_str)
        self._serializers[schema_name] = ser
        return ser

    async def publish(
        self,
        topic: str,
        key: str,
        value: dict,
        *,
        schema_name: Optional[str] = None,
        schema_version: int = 1,
        headers: Optional[dict] = None,
    ) -> None:
        if not schema_name:
            raise ValueError("KafkaBus.publish requires schema_name")
        ser = self._get_serializer(schema_name)
        kafka_headers = [(k, str(v).encode()) for k, v in (headers or {}).items()]
        kafka_headers.append(("schema_version", str(schema_version).encode()))

        ctx_v = self._SerializationContext(topic, self._MessageField.VALUE)
        ctx_k = self._SerializationContext(topic, self._MessageField.KEY)

        try:
            payload = ser(value, ctx_v)
            key_bytes = self._key_ser(key, ctx_k)
        except Exception as e:                                     # noqa: BLE001
            KAFKA_PUBLISH.labels(topic=topic, status="serialize_error").inc()
            raise

        def _cb(err, msg):
            if err is not None:
                self._delivery_errors.append(str(err))
                KAFKA_PUBLISH.labels(topic=topic, status="error").inc()
            else:
                KAFKA_PUBLISH.labels(topic=topic, status="ok").inc()

        # Fire-and-forget produce. Backpressure is handled inside
        # librdkafka (BufferError raised if local queue is full); the
        # ack/error surfaces in flush() via _delivery_errors.
        try:
            self._producer.produce(
                topic=topic,
                key=key_bytes,
                value=payload,
                headers=kafka_headers,
                on_delivery=_cb,
            )
        except BufferError:
            # Local queue full — drain it and retry once.
            self._producer.poll(1.0)
            self._producer.produce(
                topic=topic, key=key_bytes, value=payload,
                headers=kafka_headers, on_delivery=_cb,
            )
        # Drain any callbacks for messages already acked.
        self._producer.poll(0)

    async def flush(self, timeout_s: float = 10.0) -> None:
        loop = asyncio.get_event_loop()
        remaining = await loop.run_in_executor(None, self._producer.flush, timeout_s)
        if remaining and remaining > 0:
            raise RuntimeError(
                f"Kafka flush timed out: {remaining} message(s) unsent "
                f"after {timeout_s}s"
            )
        if self._delivery_errors:
            errs = self._delivery_errors[:]
            self._delivery_errors.clear()
            raise RuntimeError(
                f"Kafka delivery failed for {len(errs)} message(s): "
                f"{errs[:3]}"
            )

    async def close(self) -> None:
        await self.flush(5.0)


# ── Factory ─────────────────────────────────────────────────────────
_bus: Optional[EventBus] = None


def get_bus() -> EventBus:
    global _bus
    if _bus is not None:
        return _bus
    choice = (os.environ.get("NIDP_EVENT_BUS") or "local").lower()
    if choice == "kafka":
        # Kafka path was deprecated 2026-05-09 after the Redpanda broker on
        # the GCE VM proved unreliable and stalled every Cloud Run job at
        # bus.flush() with broker-timeout errors. We force the local bus
        # regardless of NIDP_EVENT_BUS to keep ingestion green.
        # Re-enable by reverting this block once a managed broker
        # (Pub/Sub or Confluent Cloud) is in place.
        logger.warning(
            "Event bus: NIDP_EVENT_BUS=kafka requested but Kafka path is "
            "DISABLED. Falling back to local-log bus.")
    _bus = LocalLogBus()
    logger.info("Event bus: local-log (path=%s)", _bus.log_file)
    return _bus


def reset_bus() -> None:
    global _bus
    _bus = None


def _json_default(o: Any):
    if isinstance(o, (date, datetime)):
        return o.isoformat()
    return str(o)
