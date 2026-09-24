"""One relationship authority. Absence changes warmth, never trust.

关系只有一份权威；久别影响当下亲近表达，不降低信任。
"""

from typing import TYPE_CHECKING, Any

from .models import CharacterState, Relationship
from .persistence_models import RelationshipEffect, RelationshipState

if TYPE_CHECKING:
    from .knowledge import Knowledge


class Relationships:
    """Keep participant relationship authority separate from compatibility projections.

    将参与者关系权威与兼容投影分开。
    """

    def __init__(self, knowledge: "Knowledge") -> None:
        self.k = knowledge

    def get(self, cid: str) -> RelationshipState:
        """Load canonical relationship state or initialize it from the same audience's legacy state.

        读取规范关系，或从同一受众的旧状态初始化。
        """

        stored = self.k.storage.get(self.k.owner, "relationship", cid)
        if stored:
            return RelationshipState.model_validate(stored)
        legacy = self.k.characters.state(cid).relationship
        state = RelationshipState(character_id=cid, anchor=legacy, learned=legacy)
        self.save(state)
        return state

    def save(self, state: RelationshipState) -> None:
        """Save the canonical relationship and update its read compatibility projection.

        保存规范关系并更新兼容读取投影。
        """

        self.k.storage.put(
            self.k.owner, "relationship", state.character_id, state.model_dump(mode="json")
        )
        # Compatibility projection only. RelationshipState remains the authority.
        legacy = self.k.characters.state(state.character_id)
        legacy.relationship = state.override or state.learned
        self.k.characters.save_state(legacy)

    def configure(self, cid: str, value: Relationship, revision: int) -> CharacterState:
        """Apply an explicit relationship override with revision conflict detection.

        执行显式关系覆盖并检测版本冲突。
        """

        with self.k.storage.transaction():
            legacy = self.k.characters.state(cid)
            if legacy.revision != revision:
                raise ValueError("State revision conflict")
            state = self.get(cid)
            state.override = value
            state.revision += 1
            self.save(state)
            legacy = self.k.characters.state(cid)
            legacy.revision += 1
            self.k.characters.save_state(legacy)
            return legacy

    def effect(self, cid: str, effect: RelationshipEffect) -> None:
        """Require independent direct-user evidence, cooldown and unused evidence for adaptation.

        关系变化要求独立直接用户证据、冷却及未重复使用的证据。
        """

        companion = self.k.storage.get(self.k.owner, "companion", cid) or {}
        if not companion.get("settings", {}).get("relationship_growth", True):
            raise ValueError("Automatic relationship growth is disabled")
        state = self.get(cid)
        events = self.k.personal_evidence(cid, effect.evidence_refs)
        if any(e.source_kind != "USER_DIRECT" for e in events):
            raise ValueError("Relationship effects require direct user evidence")
        if len({e.timestamp.date() for e in events}) < 3:
            raise ValueError("Relationship effects need independent evidence across three days")
        if set(effect.evidence_refs) & set(state.evidence_refs):
            raise ValueError("Relationship evidence cannot be repeatedly reinforced")
        instant = self.k.clock()
        if state.last_transition and (instant - state.last_transition).total_seconds() < 86400:
            raise ValueError("Relationship transition cooldown is active")
        if state.override is not None:
            raise ValueError("Explicit relationship override blocks automatic changes")
        delta = 1 if effect.direction == "increase" else -1
        if effect.dimension in ("trust", "familiarity"):
            levels = ["low", "medium", "high"]
            current = getattr(state.learned, effect.dimension)
            setattr(
                state.learned,
                effect.dimension,
                levels[max(0, min(2, levels.index(current) + delta))],
            )
        else:
            setattr(
                state,
                effect.dimension,
                max(0, min(1, getattr(state, effect.dimension) + delta * 0.1)),
            )
        stages = ["stranger", "acquaintance", "familiar", "close"]
        level = min(
            ["low", "medium", "high"].index(state.learned.trust),
            ["low", "medium", "high"].index(state.learned.familiarity),
        )
        state.learned.stage = stages[min(level + (state.closeness >= 0.7), 3)]  # type: ignore[assignment]
        state.evidence_refs = (state.evidence_refs + effect.evidence_refs)[-100:]
        state.last_transition = state.last_meaningful_interaction = instant
        state.revision += 1
        self.save(state)

    def projection(self, cid: str) -> dict[str, Any]:
        """Project bounded relational cues; absence does not rewrite learned trust.

        投影有界关系线索；久别不改写已形成的信任。
        """

        state = self.get(cid)
        days = (
            (self.k.clock() - state.last_interaction).total_seconds() / 86400
            if state.last_interaction
            else 0
        )
        return {
            **(state.override or state.learned).model_dump(),
            "closeness": "close" if state.closeness >= 0.7 else "developing",
            "friction": "elevated" if state.friction >= 0.5 else "low",
            "transient_warmth": "reconnecting" if days > 14 else "present",
            "explicit_override": state.override is not None,
        }
