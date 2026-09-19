import json
import unittest
from pathlib import Path

from character_runtime.models import CharacterDefinition, CharacterState, Memory, Package


class SchemaFilesTests(unittest.TestCase):
    def test_published_contracts_match_models_and_example(self):
        root = Path(__file__).resolve().parents[1]
        for model in (CharacterDefinition, CharacterState, Memory, Package):
            with self.subTest(model=model.__name__):
                published = json.loads((root / "schemas" / f"{model.__name__}.v1.json").read_text())
                published.pop("$schema")
                self.assertEqual(published, model.model_json_schema())
        CharacterDefinition.model_validate_json(
            (root / "examples" / "original-character.json").read_text(encoding="utf-8")
        )
