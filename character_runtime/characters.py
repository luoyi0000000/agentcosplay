"""Definition and state ownership, source precedence, and explicit configuration."""

from __future__ import annotations

from typing import Any

from .compiler import compile
from .models import CharacterDefinition, CharacterState, Fact, Relationship
from .storage import Storage

SOURCE_PRIORITY = {
    "inferred": 0,
    "model": 1,
    "wiki": 2,
    "official": 3,
    "user_material": 4,
    "user_explicit": 5,
}


class Characters:
    def __init__(self, storage: Storage, owner: str) -> None:
        self.storage, self.owner = storage, owner

    def create(self, definition: CharacterDefinition) -> CharacterDefinition:
        definition = CharacterDefinition.model_validate(definition.model_dump())
        with self.storage.transaction():
            if self.storage.get(self.owner, "definition", definition.id):
                raise ValueError("Character ID already exists; import as a new character")
            self.storage.put(
                self.owner, "definition", definition.id, definition.model_dump(mode="json")
            )
            self.save_state(CharacterState(character_id=definition.id))
            compile(self.storage, self.owner, definition)
        return definition

    def get(self, character_id: str) -> CharacterDefinition:
        value = self.storage.get(self.owner, "definition", character_id)
        if value is None:
            raise KeyError("Character not found")
        return CharacterDefinition.model_validate(value)

    def list(self) -> list[CharacterDefinition]:
        return [
            CharacterDefinition.model_validate(x)
            for x in self.storage.list(self.owner, "definition")
        ]

    def state(self, character_id: str) -> CharacterState:
        self.get(character_id)
        value = self.storage.get(self.owner, "state", character_id)
        if value is None:
            raise KeyError("Character state not found")
        return CharacterState.model_validate(value)

    def save_state(self, state: CharacterState) -> None:
        state = CharacterState.model_validate(state.model_dump())
        self.get(state.character_id)
        self.storage.put(self.owner, "state", state.character_id, state.model_dump(mode="json"))

    def update(
        self,
        character_id: str,
        *,
        expected_revision: int | None = None,
        facts: dict[str, Fact] | None = None,
        **changes: Any,
    ) -> CharacterDefinition:
        if set(changes) - {
            "name",
            "origin",
            "mode",
            "default_task_mode",
            "growth",
            "voice",
            "embodiment",
        }:
            raise ValueError("Only definition configuration may be edited here")
        with self.storage.transaction():
            old = self.get(character_id)
            if expected_revision is not None and old.revision != expected_revision:
                raise ValueError("Revision conflict; reload before editing")
            data = old.model_dump()
            merged = dict(old.facts)
            for key, incoming in (facts or {}).items():
                fact = Fact.model_validate(incoming.model_dump())
                if (
                    key in merged
                    and SOURCE_PRIORITY[fact.source_type] < SOURCE_PRIORITY[merged[key].source_type]
                ):
                    raise ValueError("Lower-priority source cannot replace an existing fact")
                merged[key] = fact
            data.update(
                changes,
                facts={k: v.model_dump() for k, v in merged.items()},
                revision=old.revision + 1,
            )
            updated = CharacterDefinition.model_validate(data)
            self.storage.put(
                self.owner, "definition", character_id, updated.model_dump(mode="json")
            )
            compiled = compile(self.storage, self.owner, updated)
            if compiled.character_version != updated.revision:
                raise ValueError("Definition compilation failed; last known good remains active")
            return updated

    def configure_relationship(
        self, character_id: str, relationship: Relationship, expected_revision: int
    ) -> CharacterState:
        """Compatibility entry; all relationship writes route to the single engine."""
        from .knowledge import Knowledge
        from .memory import Memories

        return Knowledge(
            self.storage, self.owner, self, Memories(self.storage, self.owner, self)
        ).relationship.configure(character_id, relationship, expected_revision)
