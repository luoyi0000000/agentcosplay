"""Small local state engines; perception and simulation never assert lived reality.

小型本地状态引擎；感知和模拟都不能冒充亲历现实。
"""

from datetime import timedelta
from typing import TYPE_CHECKING, Any

from .lifelike_models import (
    AffectEffect,
    AffectState,
    InteractionRequest,
    LifelikeState,
    PerceptionObservation,
    VisualPrototype,
)
from .models import new_id
from .safety import check_content

if TYPE_CHECKING:
    from .knowledge import Knowledge


class Lifelike:
    """Maintain scoped AffectState and life projections, never legacy Mood authority.

    维护作用域内 AffectState 和生活投影，不使用旧 Mood 作为权威。
    """

    def __init__(self, knowledge: "Knowledge") -> None:
        self.k = knowledge

    def get(self, cid: str) -> LifelikeState:
        """Read or initialize the scoped canonical lifelike state.

        读取或初始化当前作用域的规范生活状态。
        """

        self.k.characters.get(cid)
        value = self.k.storage.get(self.k.owner, "lifelike", cid)
        return (
            LifelikeState.model_validate(value)
            if value
            else LifelikeState(
                character_id=cid,
                updated_at=self.k.clock(),
                affect=AffectState(updated_at=self.k.clock()),
            )
        )

    def save(self, state: LifelikeState) -> None:
        """Persist validated state in the same authorized namespace.

        把验证后的状态保存到同一授权命名空间。
        """

        self.k.storage.put(
            self.k.owner, "lifelike", state.character_id, state.model_dump(mode="json")
        )

    def advance(self, cid: str) -> LifelikeState:
        """Apply bounded temporal changes to canonical state using the Runtime clock.

        依据 Runtime 时钟对规范状态应用有界时间变化。
        """

        state, instant = self.get(cid), self.k.clock()
        hours = max(0, min(72, (instant - state.updated_at).total_seconds() / 3600))
        affect_hours = max(0, (instant - state.affect.updated_at).total_seconds() / 3600)
        state.affect.valence *= 0.5 ** (affect_hours / 6)
        state.affect.arousal = 0.3 + (state.affect.arousal - 0.3) * 0.5 ** (affect_hours / 6)
        state.affect.updated_at = max(instant, state.affect.updated_at)
        profile = self.k.characters.get(cid).embodiment
        companion = self.k.storage.get(self.k.owner, "companion", cid) or {}
        simulation = companion.get("settings", {}).get("life_simulation", False)
        if profile.enabled and simulation:
            activity = companion.get("life", {}).get("activity", "idle")
            if profile.sleep_enabled:
                state.fatigue = max(
                    0, min(1, state.fatigue + hours * (-0.1 if activity == "resting" else 0.025))
                )
            if profile.hunger_enabled:
                state.hunger = max(
                    0, min(1, state.hunger + hours * (-0.3 if activity == "eating" else 0.025))
                )
            if profile.social_capacity_enabled:
                state.social_capacity = max(0.1, 1 - state.fatigue * 0.6)
            weather = companion.get("observations", {}).get("weather", {})
            if (
                profile.physical_discomfort_enabled
                and weather.get("expires_at", "") > instant.isoformat()
                and companion.get("settings", {}).get("weather_awareness")
            ):
                state.discomfort = profile.weather_sensitivity * (
                    0.5 if weather.get("condition") in ("storm", "snow") else 0
                )
            state.custom_axes = dict(profile.custom_axes)
        else:
            state.fatigue = state.hunger = state.discomfort = 0
            state.social_capacity = 1
        state.updated_at = max(instant, state.updated_at)
        self.save(state)
        return state

    def affect(self, cid: str, effect: AffectEffect) -> None:
        """Reduce evidence-backed AffectEffect into the sole current AffectState.

        把有证据的 AffectEffect 归约到唯一当前 AffectState。
        """

        events = self.k.personal_evidence(cid, effect.evidence_refs)
        if any(e.source_kind in {"SIMULATED", "PLANNED"} for e in events):
            raise ValueError("Planned or simulated interactions cannot supply interpersonal affect")
        check_content(effect.model_dump_json())
        state = self.advance(cid)
        if set(effect.evidence_refs) & set(state.affect.evidence_refs):
            raise ValueError("Affect evidence was already applied")
        if (
            state.affect.influenced_at
            and (self.k.clock() - state.affect.influenced_at).total_seconds() < 60
        ):
            raise ValueError("Affect influence cooldown is active")
        for axis in ("valence", "arousal", "vulnerability", "confidence"):
            setattr(
                state.affect,
                axis,
                max(
                    -1 if axis == "valence" else 0,
                    min(1, getattr(state.affect, axis) + getattr(effect, axis)),
                ),
            )
        state.affect.tags = effect.tags
        state.affect.evidence_refs = (state.affect.evidence_refs + effect.evidence_refs)[-100:]
        state.affect.influenced_at = self.k.clock()
        self.save(state)

    def projection(self, cid: str, focus: str = "current conversation") -> dict[str, Any]:
        """Return current bounded state for context, not historical Mood labels.

        返回用于上下文的有界当前状态，不返回旧 Mood 标签。
        """

        state = self.advance(cid)
        relationship = self.k.relationship.projection(cid)
        profile = self.k.characters.get(cid).embodiment
        return {
            "affect": {
                "tone": "warm"
                if state.affect.valence > 0.2
                else "subdued"
                if state.affect.valence < -0.2
                else "steady",
                "energy": "animated" if state.affect.arousal > 0.6 else "calm",
                "tags": state.affect.tags,
            },
            "attention": {
                "care": "familiar" if relationship["stage"] != "stranger" else "respectful",
                "focus": focus,
                "capacity": "limited"
                if state.social_capacity - state.affect.vulnerability * 0.2 - state.discomfort * 0.2
                < 0.5
                else "available",
            },
            "embodiment": {
                "enabled": profile.enabled,
                "source": "simulated_life",
                "tired": profile.enabled and state.fatigue > 0.7,
                "hungry": profile.enabled and state.hunger > 0.7,
            },
        }

    def observe(self, observation: PerceptionObservation) -> dict[str, Any]:
        """Accept a bounded perception observation without granting factual authority.

        接受有界感知观察，不因此授予事实权威。
        """

        cid = observation.character_id
        events = self.k.evidence(cid, observation.evidence_refs)
        if any(e.source_kind != "MEDIA_DERIVED" for e in events):
            raise ValueError("Perception requires media-derived RawEvents")
        if not observation.observed_at <= self.k.clock() < observation.expires_at:
            raise ValueError("Perception timestamps must be current")
        if observation.expires_at - observation.observed_at > timedelta(days=1):
            raise ValueError("Perception freshness is limited to one day")
        check_content(observation.model_dump_json())
        if observation.recognized == "SELF":
            prototype = self.k.storage.get(
                self.k.owner, "visual_prototype", observation.prototype_id or ""
            )
            if (
                not prototype
                or prototype.get("character_id") != cid
                or prototype.get("status") != "trusted"
                or observation.confidence < 0.8
            ):
                observation.recognized = "UNKNOWN"
        self.k.storage.put(
            self.k.owner, "perception", observation.id, observation.model_dump(mode="json")
        )
        return {
            "observation_id": observation.id,
            "recognized": observation.recognized,
            "source": "MEDIA",
        }

    def prototype(self, cid: str, proposal: VisualPrototype, *, explicit: bool) -> dict[str, Any]:
        """Read the owned visual prototype separately from identity evidence.

        读取所属视觉原型，与身份证据分离。
        """

        if proposal.character_id != cid:
            raise ValueError("Visual prototype scope mismatch")
        events = self.k.evidence(cid, proposal.evidence_refs)
        if explicit and not any(e.source_kind == "USER_DIRECT" for e in events):
            raise ValueError("Trusted prototype requires explicit direct user evidence")
        if not explicit and not any(e.source_kind == "MEDIA_DERIVED" for e in events):
            raise ValueError("Candidate prototype requires media evidence")
        existing = self.k.records("visual_prototype", cid)
        if len(existing) >= 50:
            raise ValueError(
                "Prototype capacity reached; canonical references are never auto-evicted"
            )
        if self.k.storage.get(self.k.owner, "visual_prototype", proposal.id):
            raise ValueError("Prototype already exists; use an issued update grant")
        check_content(proposal.model_dump_json())
        proposal.status = "trusted" if explicit else "candidate"
        proposal.authority = "USER_EXPLICIT" if explicit else "HOST_OBSERVED"
        self.k.storage.put(
            self.k.owner, "visual_prototype", proposal.id, proposal.model_dump(mode="json")
        )
        return {"prototype_id": proposal.id, "status": proposal.status}


def interaction(request: InteractionRequest) -> dict[str, Any]:
    """Choose a supported interaction form without authorizing a platform send.

    选择平台支持的互动形式，不授予实际发送权限。
    """

    chosen = (
        request.preferred
        if request.preferred in request.capabilities
        else ("TEXT" if "TEXT" in request.capabilities else "SILENCE")
    )
    return {
        "intent": chosen,
        "purpose": request.purpose,
        "delivery": "host_adapter",
        "id": new_id(),
        "send_authorized": False,
    }
