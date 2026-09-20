"""Regenerate versioned JSON Schema files from the public contracts."""

import json
from pathlib import Path

from character_runtime.companion_models import CompanionState
from character_runtime.models import CharacterDefinition, CharacterState, Memory, Package
from character_runtime.packages import PackageV2
from character_runtime.providers import Observation


def main() -> None:
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
    for name, model in models.items():
        data = model.model_json_schema()
        data["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        (root / f"{name}.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
