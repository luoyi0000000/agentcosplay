# Generic host adapter

Use the agentcosplay MCP backend as the only character state store. Apply the workflow in `plugins/agentcosplay/skills/agentcosplay/SKILL.md` through your host's instruction/skill mechanism. The host provides language understanding and generation; the runtime provides typed state, persistence and deterministic boundaries.

Open a distinct session per conversation, load context before each active reply, commit selected candidate memories once per completed turn, and never promote roleplay to real user facts without explicit user confirmation. Tool errors mean the operation did not succeed. All HTTP identities come from authentication; never send user IDs in tool arguments.

If a host can guarantee before/after-turn hooks, invoke the same operations there. Plain MCP capability alone does not guarantee an LLM will invoke them every turn. Evaluate omission/retry/OOC cases on each host. Do not copy the database or implement another platform-specific memory system.
