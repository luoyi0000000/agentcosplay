"""Versioned portable packages; no transport credentials or foreign grants survive import."""

import json
from copy import deepcopy
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from .companion_models import CompanionState, Goal, Habit, Mood, Settings, Topic
from .knowledge_models import FactRecord, RawEvent
from .lifelike_models import LifelikeState, VisualPrototype
from .models import (
    Authority,
    CharacterDefinition,
    CharacterState,
    Identifier,
    Memory,
    Model,
    Package,
    Text,
    new_id,
    now,
)
from .persistence_models import GrowthCandidate, GrowthVersion, RelationshipState
from .runtime import Runtime
from .safety import check_content


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


class PortableKnowledge(Model):
    """The bounded common shape of project memories and narrative records."""

    id: Identifier
    owner_id: Identifier
    character_id: Identifier
    content: Text
    evidence_refs: list[Identifier] = Field(default_factory=list, max_length=20)
    authority: Authority = "INFERRED"
    source: str = Field(default="derived", max_length=2000)
    validity: Literal["active", "archived"] = "active"
    sensitivity: Literal["public", "private", "sensitive"] = "private"
    legacy_unverified: bool = False


class RuntimeSnapshot(Model):
    relationship: RelationshipState | None = None
    growth_versions: list[GrowthVersion] = Field(default_factory=list, max_length=1000)
    growth_candidates: list[GrowthCandidate] = Field(default_factory=list, max_length=1000)
    active_growth_version: Identifier | None = None
    lifelike: LifelikeState | None = None
    visual_prototypes: list[VisualPrototype] = Field(default_factory=list, max_length=50)


class PackageV3(Model):
    schema_version: Literal[3] = 3
    definition: CharacterDefinition
    state: CharacterState | None = None
    memories: list[Memory] = Field(default_factory=list, max_length=10000)
    includes_memories: bool = False
    companion: CompanionState | None = None
    includes_private_knowledge: bool = False
    runtime_snapshot: RuntimeSnapshot | None = None
    raw_events: list[RawEvent] = Field(default_factory=list, max_length=10000)
    facts: list[FactRecord] = Field(default_factory=list, max_length=10000)
    narrative: list[PortableKnowledge] = Field(default_factory=list, max_length=10000)
    project_memories: list[PortableKnowledge] = Field(default_factory=list, max_length=10000)

    @model_validator(mode="after")
    def coherent(self) -> Self:
        PackageV2.model_validate(
            self.model_dump(include=set(PackageV2.model_fields)) | {"schema_version": 2}
        )
        if self.runtime_snapshot:
            if not self.includes_private_knowledge:
                raise ValueError("Runtime snapshot requires explicit private export opt-in")
            snapshot_records: list[GrowthVersion | GrowthCandidate | VisualPrototype] = [
                *self.runtime_snapshot.growth_versions,
                *self.runtime_snapshot.growth_candidates,
                *self.runtime_snapshot.visual_prototypes,
            ]
            if any(r.character_id != self.definition.id for r in snapshot_records):
                raise ValueError("Snapshot record namespace mismatch")
            for r in (self.runtime_snapshot.relationship, self.runtime_snapshot.lifelike):
                if r and r.character_id != self.definition.id:
                    raise ValueError("Snapshot state namespace mismatch")
            if self.runtime_snapshot.active_growth_version and not any(
                v.id == self.runtime_snapshot.active_growth_version
                for v in self.runtime_snapshot.growth_versions
            ):
                raise ValueError("Active growth version is absent from snapshot")
        records: list[RawEvent | FactRecord | PortableKnowledge] = [
            *self.raw_events,
            *self.facts,
            *self.narrative,
            *self.project_memories,
        ]
        if records and not self.includes_private_knowledge:
            raise ValueError("Private knowledge requires an explicit export opt-in")
        if any(r.character_id != self.definition.id for r in records):
            raise ValueError("Private knowledge belongs to another character")
        ids = [r.id for r in records] + [m.id for m in self.memories]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate package record IDs")
        evidence = {r.id for r in self.raw_events if r.validity == "active"}
        evidenced: list[Memory | FactRecord | PortableKnowledge] = [
            *self.memories,
            *self.facts,
            *self.narrative,
            *self.project_memories,
        ]
        if any(ref not in evidence for r in evidenced for ref in r.evidence_refs):
            raise ValueError("Evidence must reference a scoped RawEvent included in the package")
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
    evidenced: list[Mood | Goal | Habit | Topic] = [
        result.mood,
        *result.goals,
        *result.habits,
        *result.topics,
    ]
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
    include_private_knowledge: bool = False,
) -> PackageV3:
    if include_companion and not include_memories:
        raise ValueError("Companion contains private activity; explicit memory opt-in is required")
    with runtime.storage.transaction():
        definition = runtime.characters.get(character_id)
        state = runtime.characters.state(character_id)
        raw_events: list[RawEvent] = []
        facts: list[FactRecord] = []
        private: dict[str, list[PortableKnowledge]] = {"narrative": [], "project_memory": []}
        if include_private_knowledge:
            for data in runtime.storage.list(runtime.owner, "raw_event"):
                if data.get("character_id") == character_id and data.get("validity") == "active":
                    event = RawEvent.model_validate(data)
                    if event.owner_id != runtime.owner:
                        raise ValueError("RawEvent owner does not match the export namespace")
                    raw_events.append(
                        RawEvent.model_validate(
                            event.model_dump()
                            | {
                                "owner_id": "export",
                                "session_id": "export",
                                "source_id": "export",
                                "source_event_id": event.id,
                                "host": "",
                                "platform": "",
                                "conversation_id": "",
                                "actor_id": "",
                                "source_ref": "",
                            }
                        )
                    )
            for data in runtime.storage.list(runtime.owner, "fact"):
                if data.get("character_id") == character_id and data.get("validity") in {
                    "active",
                    "archived",
                    "superseded",
                }:
                    facts.append(
                        FactRecord.model_validate(
                            data
                            | {
                                "owner_id": "export",
                                "superseded_by": None,
                            }
                        )
                    )
            for collection, records in private.items():
                for data in runtime.storage.list(runtime.owner, collection):
                    if data.get("character_id") == character_id and data.get("validity") in {
                        "active",
                        "archived",
                    }:
                        records.append(
                            PortableKnowledge.model_validate(
                                data
                                | {
                                    "owner_id": "export",
                                    "source": "exported_package",
                                }
                            )
                        )
        evidence = {e.id for e in raw_events}
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
                        "session_id": None,
                        "promoted_from": None,
                        "turn_id": None,
                        "observation_turn_ids": [],
                        "confirmation": "",
                        "source": "simulated_life"
                        if m.source == "simulated_life"
                        else "exported_package",
                        "evidence_refs": [ref for ref in m.evidence_refs if ref in evidence],
                    }
                    if not m.evidence_refs or any(ref not in evidence for ref in m.evidence_refs):
                        data.update(legacy_unverified=True, authority="INFERRED")
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
        snapshot = None
        if include_private_knowledge:
            version, _ = runtime.knowledge.growth.current(character_id)
            snapshot = RuntimeSnapshot(
                relationship=runtime.knowledge.relationship.get(character_id),
                growth_versions=[
                    GrowthVersion.model_validate(r)
                    for r in runtime.knowledge.records("growth_version", character_id)
                ],
                growth_candidates=[
                    GrowthCandidate.model_validate(r)
                    for r in runtime.knowledge.records("growth_candidate", character_id)
                ],
                active_growth_version=None if version == "baseline" else version,
                lifelike=runtime.knowledge.lifelike.get(character_id),
                visual_prototypes=[
                    VisualPrototype.model_validate(r)
                    for r in runtime.knowledge.records("visual_prototype", character_id)
                ],
            )
        return PackageV3(
            runtime_snapshot=snapshot,
            definition=definition,
            state=state,
            memories=memories,
            includes_memories=include_memories,
            companion=portable_companion(
                runtime.companion.get(character_id), {i: i for i in ids | evidence}, character_id
            )
            if include_companion
            else None,
            includes_private_knowledge=include_private_knowledge,
            raw_events=raw_events,
            facts=facts,
            narrative=private["narrative"],
            project_memories=private["project_memory"],
        )


def migrate_package(data: dict[str, Any]) -> dict[str, Any]:
    """Non-destructive V1/V2→V3 conversion; the input remains an exact backup.

    Never rewrites a package file or an existing character/database record.
    """
    source = deepcopy(data)
    if source.get("schema_version") == 1:
        Package.model_validate(source)
        source.update(schema_version=2, companion=None)
    if source.get("schema_version") == 2:
        package = PackageV2.model_validate(source)
        source = package.model_dump(mode="json") | {"schema_version": 3}
        for memory in source["memories"]:
            memory.update(evidence_refs=[], authority="INFERRED", legacy_unverified=True)
    elif source.get("schema_version") != 3:
        raise ValueError("Unsupported package version; only V1, V2 and V3 are accepted")
    return source


def import_character(
    runtime: Runtime, data: dict[str, Any], *, sensitive_confirmation: str = ""
) -> CharacterDefinition:
    if len(json.dumps(data, ensure_ascii=False).encode()) > 10_000_000:
        raise ValueError("Character package exceeds 10 MB")
    package = PackageV3.model_validate(migrate_package(data))
    _check_import_content(package.model_dump(mode="json"), bool(sensitive_confirmation.strip()))
    new_character = new_id()
    mapping = {m.id: new_id() for m in package.memories}
    raw_mapping = {e.id: new_id() for e in package.raw_events}
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
                    "promoted_from": None,
                    "confirmation": "",
                    "kind": "character_long_term" if m.kind == "shared_roleplay" else m.kind,
                    "source": "imported_package",
                    "authority": "INFERRED",
                    "legacy_unverified": True,
                    "evidence_refs": [raw_mapping[ref] for ref in m.evidence_refs],
                    "session_id": None,
                    "turn_id": None,
                    "observation_turn_ids": [],
                    "last_access": None,
                }
            )
        )
    with runtime.storage.transaction():
        runtime.characters.create(definition)
        runtime.characters.save_state(state)
        for m in memories:
            runtime.storage.put(runtime.owner, "memory", m.id, m.model_dump(mode="json"))
        import_session = new_id()
        import_source = new_id()
        for event in package.raw_events:
            if event.validity != "active":
                raise ValueError("Only active RawEvent bodies are portable")
            imported = RawEvent.model_validate(
                event.model_dump()
                | {
                    "id": raw_mapping[event.id],
                    "owner_id": runtime.owner,
                    "character_id": new_character,
                    "session_id": import_session,
                    "source_id": import_source,
                    "source_event_id": new_id(),
                    "source_kind": "FORWARDED",
                    "legacy_unverified": True,
                    "host": "",
                    "platform": "",
                    "conversation_id": "",
                    "actor_id": "",
                    "source_ref": "",
                    "received_at": now(),
                }
            )
            runtime.storage.put(
                runtime.owner, "raw_event", imported.id, imported.model_dump(mode="json")
            )
        for collection, records in (
            ("fact", package.facts),
            ("narrative", package.narrative),
            ("project_memory", package.project_memories),
        ):
            for record in records:
                record_data = record.model_dump(mode="json") | {
                    "id": new_id(),
                    "owner_id": runtime.owner,
                    "character_id": new_character,
                    "evidence_refs": [raw_mapping[ref] for ref in record.evidence_refs],
                    "authority": "INFERRED",
                    "legacy_unverified": True,
                    "validity": "archived",
                }
                if collection == "fact":
                    record_data.update(superseded_by=None)
                else:
                    record_data.update(source="imported_package")
                runtime.storage.put(runtime.owner, collection, record_data["id"], record_data)
        if package.runtime_snapshot:
            snapshot = package.runtime_snapshot
            # Preserve full imported history as non-authoritative, owner-local archival data.
            runtime.storage.put(
                runtime.owner,
                "imported_snapshot",
                new_character,
                {
                    "character_id": new_character,
                    "snapshot": snapshot.model_dump(mode="json"),
                    "authority": "USER_MANUAL",
                    "evidence_is_unverified": True,
                },
            )
            if snapshot.relationship:
                relationship = snapshot.relationship.model_copy(deep=True)
                relationship.character_id = new_character
                relationship.evidence_refs = []
                relationship.last_interaction = relationship.last_transition = None
                runtime.knowledge.relationship.save(relationship)
            current = next(
                (v for v in snapshot.growth_versions if v.id == snapshot.active_growth_version),
                None,
            )
            if current:
                imported_growth = GrowthVersion(
                    character_id=new_character,
                    overlay=current.overlay,
                    reason="Imported character configuration; historical evidence remains archival",
                    impact="high",
                    approved_by="USER_EXPLICIT",
                )
                runtime.knowledge.growth._promote(imported_growth)
            if snapshot.lifelike:
                lifelike = snapshot.lifelike.model_copy(deep=True)
                lifelike.character_id = new_character
                lifelike.affect.evidence_refs = []
                lifelike.updated_at = now()
                runtime.knowledge.lifelike.save(lifelike)
            for prototype in snapshot.visual_prototypes:
                value = prototype.model_dump(mode="json") | {
                    "id": new_id(),
                    "character_id": new_character,
                    "status": "candidate",
                    "authority": "HOST_OBSERVED",
                    "evidence_refs": [
                        raw_mapping[r] for r in prototype.evidence_refs if r in raw_mapping
                    ],
                }
                if value["evidence_refs"]:
                    runtime.storage.put(runtime.owner, "visual_prototype", value["id"], value)
        if package.companion:
            companion = portable_companion(package.companion, mapping | raw_mapping, new_character)
            items: list[Goal | Habit | Topic] = [
                *companion.goals,
                *companion.habits,
                *companion.topics,
            ]
            for item in items:
                item.id = new_id()
            runtime.storage.put(
                runtime.owner, "companion", new_character, companion.model_dump(mode="json")
            )
    return definition


def _check_import_content(value: Any, confirmed: bool) -> None:
    """Every persisted string crosses the same safety gate, including legacy packages."""
    if isinstance(value, str):
        check_content(value, confirmed=confirmed)
    elif isinstance(value, list):
        for item in value:
            _check_import_content(item, confirmed)
    elif isinstance(value, dict):
        if value.get("sensitivity") == "sensitive" and not confirmed:
            raise ValueError("Sensitive personal content requires explicit storage authorization")
        for key, item in value.items():
            _check_import_content(key, confirmed)
            _check_import_content(item, confirmed)
