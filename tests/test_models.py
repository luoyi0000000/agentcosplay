import unittest

from pydantic import ValidationError

from character_runtime.models import CharacterDefinition, Fact, Memory, Package


class ModelTests(unittest.TestCase):
    def test_rejects_unknown_and_invalid_source(self):
        with self.assertRaises(ValidationError):
            Fact(value="quiet", source_type="rumor")
        with self.assertRaises(ValidationError):
            Fact(value="quiet", confidence=float("nan"))
        with self.assertRaises(ValidationError):
            CharacterDefinition(name="A", memories=[])

    def test_inference_cannot_claim_canon(self):
        with self.assertRaises(ValidationError):
            Fact(value="likes tea", source_type="inferred", canon_status="canon")

    def test_official_requires_reference(self):
        with self.assertRaises(ValidationError):
            Fact(value="quiet", source_type="official", canon_status="canon")

    def test_session_memory_requires_session(self):
        with self.assertRaises(ValidationError):
            Memory(owner="u", character_id="a", content="today", kind="session")

    def test_future_package_version_rejected(self):
        with self.assertRaises(ValidationError):
            Package(schema_version=999, definition=CharacterDefinition(name="A"))


if __name__ == "__main__":
    unittest.main()
