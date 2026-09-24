"""Regenerate versioned JSON Schema files from the public contracts."""

import argparse
import json
from pathlib import Path

from character_runtime.companion_models import CompanionState
from character_runtime.context_models import CompiledContext, ContextBudget, ContextFragment
from character_runtime.conversation_models import (
    EndpointCapabilities,
    InteractionPlan,
    SemanticResponse,
)
from character_runtime.knowledge_models import (
    EventBatch,
    FactRecord,
    MemoryMutation,
    RawEvent,
    TurnProposal,
)
from character_runtime.lifecycle import HostCapabilities, TurnEnvelope
from character_runtime.lifelike_models import (
    InteractionRequest,
    LifelikeState,
    PerceptionObservation,
    VisualPrototype,
)
from character_runtime.models import (
    CharacterDefinition,
    CharacterState,
    EmbodimentProfile,
    Memory,
    Package,
    VoiceProfile,
)
from character_runtime.packages import PackageV2, PackageV3
from character_runtime.persistence_models import (
    GenerationRequest,
    GrowthCandidate,
    GrowthVersion,
    MemoryUseDecision,
    ProtectedPayload,
    RecallRequest,
    RelationshipState,
)
from character_runtime.providers import Observation


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Validate without rewriting files")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1] / "schemas"
    root.mkdir(exist_ok=True)
    models = {
        f"{model.__name__}.v1": model
        for model in (
            CharacterDefinition,
            CharacterState,
            Memory,
            Package,
            CompanionState,
            Observation,
        )
    }
    models["Package.v2"] = PackageV2
    models["Package.v3"] = PackageV3
    models.update(
        {
            f"{m.__name__}.v2": m
            for m in (
                ContextBudget,
                HostCapabilities,
                TurnEnvelope,
                EndpointCapabilities,
                InteractionPlan,
                SemanticResponse,
                ContextFragment,
                CompiledContext,
                RawEvent,
                FactRecord,
                EventBatch,
                TurnProposal,
                MemoryMutation,
            )
        }
    )
    models.update(
        {
            f"{m.__name__}.v2": m
            for m in (
                RelationshipState,
                GrowthCandidate,
                GrowthVersion,
                GenerationRequest,
                RecallRequest,
                MemoryUseDecision,
                ProtectedPayload,
                LifelikeState,
                PerceptionObservation,
                VisualPrototype,
                InteractionRequest,
                VoiceProfile,
                EmbodimentProfile,
            )
        }
    )
    for name, model in models.items():
        data = model.model_json_schema()
        data["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        path = root / f"{name}.json"
        if args.check:
            if not path.exists() or json.loads(path.read_text(encoding="utf-8")) != data:
                raise SystemExit(f"Schema differs from runtime contract: {path.name}")
        else:
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(models)} schemas {'verified' if args.check else 'generated'}")


if __name__ == "__main__":
    main()
