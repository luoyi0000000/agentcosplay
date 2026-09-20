import json
import unittest
from pathlib import Path

from character_runtime.companion_models import CompanionState
from character_runtime.models import CharacterDefinition, CharacterState, Memory, Package
from character_runtime.packages import PackageV2
from character_runtime.providers import Observation


class SchemaFilesTests(unittest.TestCase):
    def test_published_contracts_match_models(self):
        root = Path(__file__).resolve().parents[1]
        models = {
            f"{m.__name__}.v1": m
            for m in (
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
            with self.subTest(model=model.__name__):
                published = json.loads((root / "schemas" / f"{name}.json").read_text())
                published.pop("$schema")
                self.assertEqual(published, model.model_json_schema())
