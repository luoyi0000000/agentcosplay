"""Regenerate versioned JSON Schema files from the public contracts."""

import json
from pathlib import Path

from character_runtime.models import CharacterDefinition, CharacterState, Memory, Package


def main() -> None:
    root = Path(__file__).resolve().parents[1] / "schemas"
    root.mkdir(exist_ok=True)
    for model in (CharacterDefinition, CharacterState, Memory, Package):
        data = model.model_json_schema()
        data["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        (root / f"{model.__name__}.v1.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
