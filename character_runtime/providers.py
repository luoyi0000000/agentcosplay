"""Host observations and explicitly configured local providers; no vendor or network coupling."""

import json
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal, Protocol, Self

from pydantic import AwareDatetime, Field, model_validator

from .models import Model, Score, now

Activity = Literal["idle", "reading", "resting", "working", "walking", "eating"]
Kind = Literal["time", "weather", "schedule", "location"]


class Observation(Model):
    schema_version: Literal[1] = 1
    confidence: Score = 1
    kind: Kind
    source: str = Field(min_length=1, max_length=200)
    summary: str = Field(max_length=500)
    observed_at: AwareDatetime
    fetched_at: AwareDatetime
    expires_at: AwareDatetime
    location_scope: str = Field(default="", max_length=100)
    condition: Literal["unknown", "clear", "rain", "snow", "storm"] = "unknown"
    activity: Activity | None = None
    availability: Literal["unknown", "available", "busy", "unavailable"] = "unknown"

    @model_validator(mode="after")
    def bounded_freshness(self) -> Self:
        maximum = timedelta(
            hours={"time": 1, "weather": 12, "schedule": 24, "location": 1}[self.kind]
        )
        if not self.observed_at <= self.fetched_at < self.expires_at:
            raise ValueError("Observation timestamps must be ordered")
        if self.expires_at - self.observed_at > maximum:
            raise ValueError("Observation freshness exceeds the provider limit")
        if self.kind in ("weather", "location") and not self.location_scope.strip():
            raise ValueError("Weather/location observations require a location scope")
        return self

    def fresh(self, instant: datetime) -> bool:
        return self.observed_at <= instant < self.expires_at and self.fetched_at <= instant


class Provider(Protocol):
    def read(self) -> Observation | None: ...


class SystemTimeProvider:
    def __init__(self, clock: Callable[[], datetime] = now) -> None:
        self.clock = clock

    def read(self) -> Observation:
        instant = self.clock()
        return Observation(
            kind="time",
            source="runtime_clock",
            summary=instant.isoformat(),
            observed_at=instant,
            fetched_at=instant,
            expires_at=instant + timedelta(minutes=1),
        )


class JSONFileProvider:
    """A user-configured local file, optionally refreshed by a self-hosted collector."""

    def __init__(self, path: Path, kind: Kind) -> None:
        self.path, self.kind = path, kind

    def read(self) -> Observation | None:
        try:
            with self.path.open("rb") as stream:
                payload = stream.read(16385)
        except FileNotFoundError:
            return None
        if len(payload) > 16384:
            raise ValueError("Provider file exceeds 16 KiB")
        observation = Observation.model_validate(json.loads(payload))
        if observation.kind != self.kind:
            raise ValueError("Provider observation kind mismatch")
        return observation
