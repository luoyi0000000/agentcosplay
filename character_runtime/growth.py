"""Bounded, evidence-backed growth without rewriting character definitions."""

from typing import Literal, cast

from .models import CharacterDefinition, CharacterState, Evolution, GrowthProposal

STAGES = ["stranger", "acquaintance", "familiar", "close"]
LEVELS = ["low", "medium", "high"]
INTERVAL = {"low": 20, "medium": 5, "high": 3}


def grow(
    definition: CharacterDefinition, state: CharacterState, proposal: GrowthProposal | None
) -> CharacterState:
    if proposal is None:
        return state
    rel = state.relationship
    for field, choices in (("stage", STAGES), ("trust", LEVELS), ("familiarity", LEVELS)):
        target = getattr(proposal, field)
        if (
            target is not None
            and abs(choices.index(target) - choices.index(getattr(rel, field))) > 1
        ):
            raise ValueError("Growth may move only to an adjacent relationship level")
    interval = INTERVAL[definition.growth.relationship_mutability]
    if state.turn_count - state.last_growth_turn.get("relationship", 0) >= interval:
        changed = False
        for field in ("stage", "trust", "familiarity"):
            target = getattr(proposal, field)
            if target is not None and target != getattr(rel, field):
                state.relationship_history.append(
                    {
                        "field": field,
                        "from": getattr(rel, field),
                        "to": target,
                        "turn": state.turn_count,
                        "evidence_ids": ",".join(proposal.evidence_ids),
                    }
                )
                setattr(rel, field, target)
                changed = True
        state.relationship_history = state.relationship_history[-100:]
        if changed:
            state.last_growth_turn["relationship"] = state.turn_count
    for axis, values, summaries, mutability in (
        (
            "personality",
            proposal.personality,
            proposal.personality_summaries,
            definition.growth.personality_mutability,
        ),
        (
            "world",
            proposal.world,
            proposal.world_summaries,
            definition.growth.world_state_mutability,
        ),
    ):
        if not values:
            continue
        if not proposal.evidence_ids:
            raise ValueError("Personality/world growth needs remembered evidence")
        for key in values:
            if key in definition.facts:
                raise ValueError("Automatic growth cannot change a definition fact; edit in OOC")
        if state.turn_count - state.last_growth_turn.get(axis, 0) < INTERVAL[mutability]:
            continue
        for key, value in values.items():
            state.evolution = [e for e in state.evolution if not (e.axis == axis and e.key == key)]
            state.evolution.append(
                Evolution(
                    axis=cast(Literal["personality", "world"], axis),
                    key=key,
                    value=value,
                    portable_summary=summaries.get(key),
                    evidence_ids=proposal.evidence_ids,
                    at_turn=state.turn_count,
                )
            )
        state.evolution = state.evolution[-100:]
        state.last_growth_turn[axis] = state.turn_count
    return state
