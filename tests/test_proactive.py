from datetime import timedelta

from tests.test_companion import CompanionFixture


class ProactiveTests(CompanionFixture):
    def prepare(self):
        self.update(
            settings={"proactive_contact": True, "timezone": "UTC"},
            topic={"id": "book", "description": "聊读书", "priority": 0.8},
        )

    def test_opt_in_reservation_ack_cooldown_duplicate(self):
        self.assertEqual(self.c.decide(self.cid).silence_reason, "disabled")
        self.prepare()
        decision = self.c.decide(self.cid)
        self.assertTrue(decision.should_contact)
        self.assertFalse(self.c.decide(self.cid).should_contact)
        self.c.ack(self.cid, decision.id, True)
        self.assertFalse(self.c.decide(self.cid).should_contact)
        self.time += timedelta(hours=7)
        self.assertEqual(self.c.decide(self.cid).silence_reason, "no_relevant_topic")

    def test_quiet_recent_availability_and_opt_out(self):
        self.prepare()
        self.time = self.time.replace(hour=23)
        self.assertEqual(self.c.decide(self.cid).silence_reason, "quiet_hours")
        self.time += timedelta(hours=13)
        self.c.record_activity(self.cid)
        self.assertEqual(self.c.decide(self.cid).silence_reason, "recent_activity")
        self.time += timedelta(hours=2)
        self.update(settings={"availability": "busy"})
        self.assertEqual(self.c.decide(self.cid).silence_reason, "unavailable")
        self.update(settings={"proactive_contact": False})
        self.assertEqual(self.c.decide(self.cid).silence_reason, "disabled")

    def test_failed_ack_retries_and_success_is_idempotent(self):
        self.prepare()
        first = self.c.decide(self.cid)
        self.c.ack(self.cid, first.id, False)
        second = self.c.decide(self.cid)
        self.assertTrue(second.should_contact)
        self.c.ack(self.cid, second.id, True)
        self.c.ack(self.cid, second.id, True)
        self.assertEqual(self.c.get(self.cid).contacts_today, 1)

    def test_daily_limit_and_delivery_recheck_after_opt_out(self):
        self.prepare()
        self.update(settings={"max_contacts_per_day": 1})
        decision = self.c.decide(self.cid)
        self.assertTrue(self.c.decide(self.cid, decision.id).should_contact)
        self.update(settings={"proactive_contact": False})
        self.assertEqual(self.c.decide(self.cid, decision.id).silence_reason, "disabled")
        self.update(settings={"proactive_contact": True})
        self.c.ack(self.cid, decision.id, True)
        self.time += timedelta(hours=7)
        self.update(topic={"id": "other", "description": "新主题", "priority": 1})
        self.assertEqual(self.c.decide(self.cid).silence_reason, "daily_limit")

    def test_stale_reservation_never_automatically_reissued(self):
        self.prepare()
        decision = self.c.decide(self.cid)
        self.time += timedelta(minutes=6)
        self.assertEqual(self.c.decide(self.cid, decision.id).silence_reason, "reservation_stale")
        self.assertEqual(self.c.decide(self.cid).silence_reason, "delivery_unconfirmed")
        with self.assertRaises(ValueError):
            self.c.ack(self.cid, "unknown", True)

    def test_concurrent_schedulers_only_one_reservation(self):
        import threading

        self.prepare()
        decisions = []
        threads = [
            threading.Thread(target=lambda: decisions.append(self.c.decide(self.cid)))
            for _ in range(4)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sum(d.should_contact for d in decisions), 1)

    def test_recent_topic_mention_extends_older_delivery_cooldown(self):
        self.prepare()
        first = self.c.decide(self.cid)
        self.c.ack(self.cid, first.id, True)
        self.time += timedelta(days=8)
        self.update(
            topic={"id": "book", "description": "聊读书", "priority": 0.8, "mentioned": True}
        )
        self.assertEqual(self.c.decide(self.cid).silence_reason, "no_relevant_topic")
