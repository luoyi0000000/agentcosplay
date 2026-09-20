"""Versioned portable packages; no transport credentials or foreign grants survive import."""

import json
from copy import deepcopy
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from .companion_models import CompanionState, Goal, Habit, Mood, Settings
from .models import CharacterDefinition, CharacterState, Memory, Model, Package, new_id, now
from .runtime import Runtime


class PackageV2(Model):
    schema_version: Literal[2] = 2
    definition: CharacterDefinition
    state: CharacterState | None = None
    memories: list[Memory] = Field(default_factory=list, max_length=10000)
    includes_memories: bool = False
    companion: CompanionState | None = None

    @model_validator(mode="after")
    def coherent(self) -> Self:
        Package.model_validate(self.model_dump(exclude={"companion", "schema_version"}))
        if self.companion and (
            not self.includes_memories or self.companion.character_id != self.definition.id
        ):
            raise ValueError("Companion export requires private-data opt-in and matching character")
        return self


def portable_companion(
    state: CompanionState, memory_ids: dict[str, str], character_id: str
) -> CompanionState:
    data = state.model_dump()
    data.update(
        character_id=character_id,
        revision=1,
        settings=Settings(),
        observations={},
        last_user_activity=None,
        last_contact_at=None,
        contact_day="",
        contacts_today=0,
        pending_decision=None,
        acknowledgements={},
        contacted_topics={},
        simulated_memories=[],
        last_advanced_at=now(),
    )
    result = CompanionState.model_validate(data)
    evidenced: list[Mood | Goal | Habit] = [result.mood, *result.goals, *result.habits]
    for item in evidenced:
        item.evidence_ids = [memory_ids[i] for i in item.evidence_ids if i in memory_ids]
    # A package cannot grant delivery/simulation authority or backdate autonomous progression.
    for goal in result.goals:
        goal.simulate = False
    return result


def export_character(
    runtime: Runtime,
    character_id: str,
    *,
    include_memories: bool = False,
    include_companion: bool = False,
) -> Package | PackageV2:
    if include_companion and not include_memories:
        raise ValueError("Companion contains private activity; explicit memory opt-in is required")
    with runtime.storage.transaction():
        definition = runtime.characters.get(character_id)
        state = runtime.characters.state(character_id)
        state.known_characters = []
        state.shared_world_id = None
        memories: list[Memory] = []
        if include_memories:
            for data in runtime.storage.list(runtime.owner, "memory"):
                m = Memory.model_validate(data)
                if (
                    m.character_id == character_id
                    and m.kind != "real_user"
                    and m.status == "active"
                    and (not m.expires_at or m.expires_at > now())
                ):
                    data = m.model_dump() | {
                        "owner": "export",
                        "scope": "private",
                        "shared_with": [],
                        "session_id": None,
                        "promoted_from": None,
                        "turn_id": None,
                    }
                    if m.kind == "session":
                        continue
                    memories.append(Memory.model_validate(data))
        ids = {m.id for m in memories}
        # State is portable; private event bodies and external references are not.
        state.relationship_history = []
        for e in state.evolution:
            if not include_memories or any(i not in ids for i in e.evidence_ids):
                # The host supplies a trait-only summary; never derive it by copying event bodies.
                e.value = e.portable_summary or "[Private growth detail omitted]"
                e.evidence_ids = []
            else:
                e.evidence_ids = [i for i in e.evidence_ids if i in ids]
        core = Package(
            definition=definition,
            state=state,
            memories=memories,
            includes_memories=include_memories,
        )
        if include_companion:
            return PackageV2.model_validate(
                core.model_dump()
                | {
                    "schema_version": 2,
                    "companion": portable_companion(
                        runtime.companion.get(character_id), {i: i for i in ids}, character_id
                    ),
                }
            )
        return core


def migrate_package(data: dict[str, Any]) -> dict[str, Any]:
    """Non-destructive V1→V2 conversion; the original input remains an exact backup.

    Never rewrites a package file or an existing character/database record.
    """
    source = deepcopy(data)
    if source.get("schema_version") == 1:
        Package.model_validate(source)
        source.update(schema_version=2, companion=None)
    elif source.get("schema_version") != 2:
        raise ValueError("Unsupported package version; only V1 and V2 are accepted")
    return source


def import_character(runtime: Runtime, data: dict[str, Any]) -> CharacterDefinition:
    if len(json.dumps(data, ensure_ascii=False).encode()) > 10_000_000:
        raise ValueError("Character package exceeds 10 MB")
    package = PackageV2.model_validate(migrate_package(data))
    new_character = new_id()
    mapping = {m.id: new_id() for m in package.memories}
    if len(mapping) != len(package.memories):
        raise ValueError("Duplicate memory IDs")
    definition = CharacterDefinition.model_validate(
        package.definition.model_dump()
        | {
            "id": new_character,
            "revision": 1,
        }
    )
    state = package.state or CharacterState(character_id=package.definition.id)
    state = CharacterState.model_validate(
        state.model_dump()
        | {
            "character_id": new_character,
            "known_characters": [],
            "shared_world_id": None,
            "revision": 1,
            "relationship_history": [],
        }
    )
    for e in state.evolution:
        if any(i not in mapping for i in e.evidence_ids):
            raise ValueError("Evolution references a memory missing from the package")
        e.evidence_ids = [mapping[i] for i in e.evidence_ids]
    memories = []
    for m in package.memories:
        if m.status != "active" or m.kind == "session":
            raise ValueError("Only active non-session character memory is portable")
        memories.append(
            Memory.model_validate(
                m.model_dump()
                | {
                    "id": mapping[m.id],
                    "owner": runtime.owner,
                    "character_id": new_character,
                    "scope": "private",
                    "shared_with": [],
                    "promoted_from": None,
                    "confirmation": "",
                    "turn_id": None,
                    "last_access": None,
                }
            )
        )
    with runtime.storage.transaction():
        runtime.characters.create(definition)
        runtime.characters.save_state(state)
        for m in memories:
            runtime.storage.put(runtime.owner, "memory", m.id, m.model_dump(mode="json"))
        if package.companion:
            companion = portable_companion(package.companion, mapping, new_character)
            runtime.storage.put(
                runtime.owner, "companion", new_character, companion.model_dump(mode="json")
            )
    return definition
