from datetime import timedelta

from character_runtime.providers import Observation, SystemTimeProvider
from tests.test_companion import CompanionFixture


class ProviderTests(CompanionFixture):
    def test_stale_and_scope_and_toggle(self):
        observation = Observation(
            kind="weather",
            source="host",
            summary="下雨",
            location_scope="上海",
            observed_at=self.time,
            fetched_at=self.time,
            expires_at=self.time + timedelta(hours=1),
            condition="rain",
        )
        self.c.observe(self.cid, observation)
        self.assertNotIn("weather", self.c.context(self.cid)["environment"])
        self.update(settings={"weather_awareness": True})
        self.assertEqual(self.c.context(self.cid)["environment"]["weather"]["source"], "host")
        self.time += timedelta(hours=2)
        self.assertNotIn("weather", self.c.context(self.cid)["environment"])
        with self.assertRaises(ValueError):
            self.c.observe(self.cid, observation)

    def test_time_provider_and_missing_gracefully(self):
        self.assertEqual(self.c.context(self.cid)["environment"], {})
        observation = SystemTimeProvider(clock=lambda: self.time).read()
        self.c.observe(self.cid, observation)
        self.assertEqual(self.c.context(self.cid)["environment"]["time"]["kind"], "time")

    def test_schedule_expiry_and_local_file_missing_or_invalid(self):
        import tempfile
        from pathlib import Path

        from character_runtime.providers import JSONFileProvider

        self.update(settings={"schedule_awareness": True})
        observation = Observation(
            kind="schedule",
            source="host calendar",
            summary="正在工作",
            observed_at=self.time,
            fetched_at=self.time,
            expires_at=self.time + timedelta(minutes=30),
            availability="busy",
            activity="working",
        )
        self.c.observe(self.cid, observation)
        self.assertIn("schedule", self.c.context(self.cid)["environment"])
        self.time += timedelta(hours=1)
        self.assertNotIn("schedule", self.c.context(self.cid)["environment"])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "provider.json"
            provider = JSONFileProvider(path, "schedule")
            self.assertEqual(self.c.refresh(self.cid, [provider]), {"0": "unavailable"})
            path.write_text("not json")
            self.assertEqual(self.c.refresh(self.cid, [provider]), {"0": "unavailable"})
            path.write_text(observation.model_dump_json())
            self.assertEqual(self.c.refresh(self.cid, [provider]), {"0": "unavailable"})
