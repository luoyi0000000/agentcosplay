"""Versioned portable packages; no transport credentials or foreign grants survive import."""

import json
from typing import Any

from .models import CharacterDefinition, CharacterState, Memory, Package, new_id, now
from .runtime import Runtime


def export_character(
    runtime: Runtime, character_id: str, *, include_memories: bool = False
) -> Package:
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
        return Package(
            definition=definition,
            state=state,
            memories=memories,
            includes_memories=include_memories,
        )


def migrate_package(data: dict[str, Any]) -> dict[str, Any]:
    """V1 has no legacy schema. Reject unknown versions instead of inventing a migration."""
    if data.get("schema_version") != 1:
        raise ValueError("Unsupported package version; only schema_version=1 is accepted")
    return data


def import_character(runtime: Runtime, data: dict[str, Any]) -> CharacterDefinition:
    if len(json.dumps(data, ensure_ascii=False).encode()) > 10_000_000:
        raise ValueError("Character package exceeds 10 MB")
    package = Package.model_validate(migrate_package(data))
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
    return definition
