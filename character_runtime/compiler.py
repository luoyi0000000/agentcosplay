"""Stable character compiler; validated SQLite records are promoted atomically.

稳定角色编译器；验证后的 SQLite 记录原子提升为当前版本。
"""

from typing import Any

from .context_models import CompiledContext, ContextBudget, canonical, fingerprint
from .models import CharacterDefinition, VoiceProfile
from .rules import BASE_RULES, MODE_RULES
from .storage import Storage

COMPILER_VERSION = "4"
_DYNAMIC_FACTS = {
    "current_time",
    "timestamp",
    "created_at",
    "current_mood",
    "mood",
    "relationship",
    "current_relationship",
    "username",
    "weather",
    "schedule",
    "memory",
    "memories",
}


def read_compiled(storage: Storage, owner: str, character_id: str) -> CompiledContext | None:
    """Read and validate the owned compiled prefix before reuse.

    复用前读取并验证所属角色的已编译前缀。
    """

    value = storage.get(owner, "compiled_lkg", character_id)
    if value is None:
        return None
    try:
        compiled = CompiledContext.model_validate(value)
    except (ValueError, TypeError):
        return None
    return compiled if compiled.character_id == character_id else None


def compile_definition(
    definition: CharacterDefinition | dict[str, Any],
    growth_version: str = "baseline",
    overlay: dict[str, dict[str, str]] | None = None,
) -> CompiledContext:
    """Validate a complete stable source without consulting runtime state.

    验证完整稳定源，不读取动态 Runtime 状态。
    """
    character_id = (
        definition.id if isinstance(definition, CharacterDefinition) else definition.get("id")
    )
    if not isinstance(character_id, str) or not character_id.strip():
        raise ValueError("Compilation requires an explicit character ID")
    validated = CharacterDefinition.model_validate(
        definition.model_dump(mode="json")
        if isinstance(definition, CharacterDefinition)
        else definition
    )
    if _DYNAMIC_FACTS.intersection(key.casefold() for key in validated.facts):
        raise ValueError("Dynamic/private runtime fields cannot enter a stable definition")
    stable_overlay = overlay if overlay is not None else {}
    if (
        not isinstance(stable_overlay, dict)
        or set(stable_overlay) - {"personality", "world", "voice"}
        or any(
            not isinstance(values, dict)
            or any(
                not isinstance(key, str)
                or not key.strip()
                or len(key) > 200
                or key.casefold() in _DYNAMIC_FACTS
                or not isinstance(value, str)
                or not value.strip()
                or len(value) > 4000
                for key, value in values.items()
            )
            for values in stable_overlay.values()
        )
    ):
        raise ValueError("Only validated stable personality/world overlays may compile")
    if stable_overlay.get("voice"):
        VoiceProfile.model_validate(validated.voice.model_dump() | stable_overlay["voice"])
    content = canonical(
        {
            "character": {
                "id": validated.id,
                "name": validated.name,
                "origin": validated.origin,
                "mode": validated.mode,
            },
            "facts": {key: fact.model_dump(mode="json") for key, fact in validated.facts.items()},
            "growth_policy": validated.growth.model_dump(mode="json"),
            "voice": validated.voice.model_dump(mode="json"),
            "default_task_mode": validated.default_task_mode,
            "rules": [*BASE_RULES, MODE_RULES[validated.mode]],
            "growth_overlay": stable_overlay,
            "character_version": validated.revision,
            "growth_version": growth_version,
            "compiler_version": COMPILER_VERSION,
        }
    )
    if len(content) > ContextBudget().stable_character:
        raise ValueError("Stable definition exceeds the context budget; reduce baseline details")
    return CompiledContext(
        character_id=validated.id,
        character_version=validated.revision,
        growth_version=growth_version,
        compiler_version=COMPILER_VERSION,
        content=content,
        fingerprint=fingerprint(content),
    )


def compile(
    storage: Storage,
    owner: str,
    definition: CharacterDefinition | dict[str, Any],
    growth_version: str = "baseline",
    overlay: dict[str, dict[str, str]] | None = None,
) -> CompiledContext:
    """Compile and promote, or retain only this owner's same-character valid prefix.

    A version tuple is immutable: changed source content requires a new character or
    growth version. Invalid initial configuration raises instead of inventing a prefix.

        编译并提升；失败时仅保留同一 Owner 同一角色的有效前缀。
    """
    character_id = (
        definition.id if isinstance(definition, CharacterDefinition) else definition.get("id")
    )
    if not isinstance(character_id, str) or not character_id.strip():
        raise ValueError("Compilation requires an explicit character ID")
    with storage.transaction():
        previous = read_compiled(storage, owner, character_id)
        try:
            compiled = compile_definition(definition, growth_version, overlay)
            version_key = fingerprint(
                canonical(
                    [
                        character_id,
                        compiled.character_version,
                        growth_version,
                        COMPILER_VERSION,
                    ]
                )
            )
            existing = storage.get(owner, "compiled_context", version_key)
            if existing is not None:
                cached = CompiledContext.model_validate(existing)
                if cached.content != compiled.content:
                    raise ValueError("Stable character source changed without a version change")
                compiled = cached
        except (ValueError, TypeError):
            if previous is None:
                raise
            return previous
        record = compiled.model_dump(mode="json")
        storage.put(owner, "compiled_context", version_key, record)
        storage.put(owner, "compiled_lkg", character_id, record)
        return compiled
