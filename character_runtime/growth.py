"""Evidence-gated versioned overlays; automatic changes never edit the baseline."""

from datetime import timedelta
from typing import TYPE_CHECKING, Any, Literal

from .compiler import compile
from .persistence_models import GrowthCandidate, GrowthVersion
from .safety import check_content

if TYPE_CHECKING:
    from .knowledge import Knowledge


class Growth:
    def __init__(self, knowledge: "Knowledge") -> None:
        self.k = knowledge

    def current(self, cid: str) -> tuple[str, dict[str, dict[str, str]]]:
        head = self.k.storage.get(self.k.owner, "growth_head", cid)
        if not head or not head.get("version"):
            return "baseline", {}
        version = self.k.storage.get(self.k.owner, "growth_version", head["version"])
        if not version or version.get("character_id") != cid:
            raise ValueError("Growth head is invalid")
        parsed = GrowthVersion.model_validate(version)
        return parsed.id, parsed.overlay

    def propose(self, candidate: GrowthCandidate) -> dict[str, Any]:
        cid = candidate.character_id
        events = self.k.evidence(cid, candidate.evidence_refs)
        if any(e.source_kind != "USER_DIRECT" for e in events):
            raise ValueError(
                "Growth requires direct user evidence, never style history or simulation"
            )
        if len({e.timestamp.date() for e in events}) < 3:
            raise ValueError("Growth requires evidence across at least three independent days")
        for previous in self.k.records("growth_version", cid):
            same_axes = {(c.domain, c.key) for c in candidate.changes} & {
                (d["domain"], d["key"]) for d in previous.get("diff", [])
            }
            if same_axes and set(candidate.evidence_refs) <= set(previous.get("evidence_refs", [])):
                raise ValueError("The same evidence cannot drive the same growth dimension again")
        definition = self.k.characters.get(cid)
        low = {"verbosity_default", "humor_style", "directness"}
        impact: Literal["low", "medium", "high"] = (
            "low"
            if all(c.domain == "voice" and c.key in low for c in candidate.changes)
            else "high"
        )
        if all(c.domain == "world" and c.key not in definition.facts for c in candidate.changes):
            impact = "medium"
        candidate.impact = impact
        candidate.status = "pending"
        check_content(candidate.model_dump_json())
        if self.k.storage.get(self.k.owner, "growth_candidate", candidate.id):
            raise ValueError("Growth candidate ID already exists")
        self.k.storage.put(
            self.k.owner, "growth_candidate", candidate.id, candidate.model_dump(mode="json")
        )
        if impact == "low":
            return self.approve(cid, candidate.id, explicit=False)
        return {"candidate_id": candidate.id, "status": "pending", "impact": impact}

    def approve(self, cid: str, candidate_id: str, *, explicit: bool) -> dict[str, Any]:
        value = self.k.storage.get(self.k.owner, "growth_candidate", candidate_id)
        if not value or value["character_id"] != cid or value["status"] != "pending":
            raise ValueError("Pending owned growth candidate required")
        candidate = GrowthCandidate.model_validate(value)
        events = self.k.evidence(cid, candidate.evidence_refs)
        if candidate.impact == "high" and not explicit:
            raise ValueError("High-impact growth needs explicit OOC approval")
        if (
            candidate.impact == "medium"
            and not explicit
            and len({e.timestamp.date() for e in events}) < 7
        ):
            raise ValueError("Medium growth needs seven independent days or explicit approval")
        head = self.k.storage.get(self.k.owner, "growth_head", cid) or {}
        if head.get("cooldown_until") and self.k.clock().isoformat() < head["cooldown_until"]:
            raise ValueError("Growth rollback cooldown is active")
        previous, overlay = self.current(cid)
        for change in candidate.changes:
            if change.domain == "voice":
                from .models import VoiceProfile

                baseline = self.k.characters.get(cid).voice.model_dump()
                baseline.update(overlay.get("voice", {}))
                baseline[change.key] = change.value
                VoiceProfile.model_validate(baseline)
            overlay.setdefault(change.domain, {})[change.key] = change.value
        version = GrowthVersion(
            character_id=cid,
            previous_version=None if previous == "baseline" else previous,
            overlay=overlay,
            diff=candidate.changes,
            evidence_refs=candidate.evidence_refs,
            impact=candidate.impact,
            reason=candidate.reason,
            approved_by="USER_EXPLICIT" if explicit else "EVIDENCE_GATE",
        )
        self._promote(version)
        candidate.status = "approved"
        self.k.storage.put(
            self.k.owner, "growth_candidate", candidate.id, candidate.model_dump(mode="json")
        )
        return {"version": version.id, "status": "approved", "candidate_id": candidate.id}

    def _promote(self, version: GrowthVersion) -> None:
        if version.previous_version is None and not self.k.storage.get(
            self.k.owner, "growth_head", version.character_id
        ):
            baseline = GrowthVersion(
                character_id=version.character_id,
                overlay={},
                reason="Baseline checkpoint",
                impact="low",
                approved_by="USER_EXPLICIT",
            )
            self.k.storage.put(
                self.k.owner, "growth_version", baseline.id, baseline.model_dump(mode="json")
            )
            version.previous_version = baseline.id
        compiled = compile(
            self.k.storage,
            self.k.owner,
            self.k.characters.get(version.character_id),
            version.id,
            version.overlay,
        )
        if compiled.growth_version != version.id:
            raise ValueError("Growth compilation failed; previous version retained")
        self.k.storage.put(
            self.k.owner, "growth_version", version.id, version.model_dump(mode="json")
        )
        self.k.storage.put(
            self.k.owner,
            "growth_head",
            version.character_id,
            {"character_id": version.character_id, "version": version.id},
        )

    def rollback(self, cid: str, target_id: str) -> dict[str, Any]:
        target = self.k.storage.get(self.k.owner, "growth_version", target_id)
        if not target or target["character_id"] != cid:
            raise ValueError("Rollback target is outside character scope")
        current, _ = self.current(cid)
        restored = GrowthVersion.model_validate(target)
        version = GrowthVersion(
            character_id=cid,
            previous_version=current,
            overlay=restored.overlay,
            reason="Explicit rollback",
            impact="high",
            approved_by="USER_EXPLICIT",
            evidence_refs=restored.evidence_refs,
        )
        self._promote(version)
        self.k.storage.put(
            self.k.owner,
            "growth_head",
            cid,
            {
                "character_id": cid,
                "version": version.id,
                "cooldown_until": (self.k.clock() + timedelta(days=7)).isoformat(),
            },
        )
        return {"version": version.id, "restored": target_id}
