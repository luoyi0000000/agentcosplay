"""Validate owner-provided Hermes routes and bind them through the public protocol.

验证 Owner 提供的 Hermes 路由，通过公开协议绑定；不从昵称推断身份。
"""

import asyncio
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Literal, Self

import yaml  # type: ignore[import-untyped]
from agentcosplay_host.hermes_adapter import HermesAdapter
from agentcosplay_host.host_client import HostBridge
from pydantic import Field, model_validator

from .models import Identifier, Model


class Actor(Model):
    """Explicit verified actor-to-person mapping. / 显式确认的 Actor 与真人映射。"""

    actor_id: Identifier
    participant_id: Identifier


class NativeRoute(Model):
    """Keep Host addresses separate from the Runtime's returned endpoint ID.
    分离宿主地址与 Runtime 返回的 Endpoint ID。
    """

    platform: Identifier
    chat_id: Identifier
    thread_id: str = Field(default="", max_length=200)
    chat_type: Literal["dm", "group", "channel", "thread"]
    runtime_platform: Identifier
    endpoint: Identifier
    kind: Literal["dm", "group"]
    character_id: Identifier
    actors: list[Actor] = Field(min_length=1, max_length=100)
    expected_revision: int | None = Field(default=None, ge=1, strict=True)

    @model_validator(mode="after")
    def audience(self) -> Self:
        """A DM has exactly one person; groups never inherit a private audience.
        私聊只绑定一个人；群聊不继承私人受众。
        """
        if self.kind != ("dm" if self.chat_type == "dm" else "group"):
            raise ValueError("Route audience mismatch")
        if self.kind == "dm" and len(self.actors) != 1:
            raise ValueError("DM requires one verified actor")
        if len({a.actor_id for a in self.actors}) != len(self.actors):
            raise ValueError("Duplicate actor")
        return self


class NativeSetup(Model):
    """Only an explicit owner-approved route file grants binding authority.
    只有经 Owner 明确确认的路由文件才授予绑定权限。
    """

    owner_verified: bool = Field(strict=True)
    host_id: Identifier
    routes: list[NativeRoute] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_routes(self) -> Self:
        """Reject ambiguity before performing any administrative write.
        管理写入前拒绝歧义与冲突映射。
        """
        if not self.owner_verified:
            raise ValueError("Owner verification required")
        routes: set[tuple[str, ...]] = set()
        endpoints: set[tuple[str, str]] = set()
        actors: dict[tuple[str, str], str] = {}
        for route in self.routes:
            key = (route.platform, route.chat_id, route.thread_id, route.chat_type)
            endpoint = (route.runtime_platform, route.endpoint)
            if key in routes or endpoint in endpoints:
                raise ValueError("Duplicate route or endpoint")
            routes.add(key)
            endpoints.add(endpoint)
            for actor in route.actors:
                actor_key = (route.runtime_platform, actor.actor_id)
                if actors.get(actor_key, actor.participant_id) != actor.participant_id:
                    raise ValueError("Conflicting participant mapping")
                actors[actor_key] = actor.participant_id
        return self


def operation(kind: str, data: dict[str, Any]) -> str:
    """Stable operation receipts make interrupted binding safe to resume.
    稳定操作回执让中断后的绑定可安全继续。
    """
    encoded = json.dumps(data, sort_keys=True, ensure_ascii=True).encode()
    return "native-hermes-" + kind + "-" + hashlib.sha256(encoded).hexdigest()


async def bind_routes(setup: NativeSetup, bridge: HostBridge) -> dict[str, Any]:
    """Bind via owner MCP; endpoint IDs must come from Runtime responses.
    通过 Owner MCP 绑定；Endpoint ID 必须来自 Runtime 回执。
    """
    routes = []
    for route in setup.routes:
        for actor in route.actors:
            identity = dict(
                host=setup.host_id,
                platform=route.runtime_platform,
                actor_id=actor.actor_id,
                participant_id=actor.participant_id,
            )
            await bridge.call(
                "identity_control",
                {
                    **identity,
                    "operation_id": operation("identity", identity),
                    "confirmation": "Owner verified the explicit installation route file",
                },
            )
        endpoint = dict(
            platform=route.runtime_platform,
            endpoint=route.endpoint,
            kind=route.kind,
            default_character_id=route.character_id,
            participant_id=route.actors[0].participant_id if route.kind == "dm" else None,
            expected_revision=route.expected_revision,
        )
        result = await bridge.call(
            "endpoint_bind",
            {
                **endpoint,
                "operation_id": operation("endpoint", endpoint),
                "confirmation": "Owner verified the explicit installation route file",
            },
        )
        routes.append(
            {
                **route.model_dump(
                    include={
                        "platform",
                        "chat_id",
                        "thread_id",
                        "chat_type",
                        "runtime_platform",
                        "kind",
                    }
                ),
                "endpoint_id": result["id"],
            }
        )
    settings = dict(
        runtime_url=bridge.url,
        token_file=str(bridge.token_file),
        host_id=setup.host_id,
        routes=routes,
    )
    HermesAdapter(bridge.url, bridge.token_file, setup.host_id, routes)
    return settings


def merge_settings(text: str, settings: dict[str, Any], *, remove: bool = False) -> str:
    """Preserve unrelated Host settings and reject conflicting owned settings.
    保留宿主其他配置；遇到既有冲突配置时拒绝覆盖。
    """
    config = yaml.safe_load(text) if text.strip() else {}
    if not isinstance(config, dict):
        raise ValueError("Host config must be a mapping")
    target = config
    for key in ("plugins", "entries", "agentcosplay"):
        target = target.setdefault(key, {})
        if not isinstance(target, dict):
            raise ValueError("Plugin configuration must be a mapping")
    if "settings" in target and target["settings"] != settings:
        raise ValueError("Existing plugin settings differ; explicit migration required")
    if remove:
        target.pop("settings", None)
    else:
        target["settings"] = settings
    return str(yaml.safe_dump(config, allow_unicode=True, sort_keys=False))


def main() -> None:
    """Use a private stdin/stdout pipe; errors never echo route or credential data.
    使用私有管道传参；错误不回显路由或凭据。
    """
    try:
        request = json.loads(sys.stdin.read(262145))
        action = request["action"]
        if action in {"settings", "remove"}:
            result: Any = merge_settings(
                request["text"], request["settings"], remove=action == "remove"
            )
        elif action == "probe":
            bridge = HostBridge(request["url"], Path(request["token_file"]))
            asyncio.run(bridge.call("character_read", {}))
            result = True
        else:
            setup = NativeSetup.model_validate(request["setup"])
            result = (
                True
                if action == "validate"
                else asyncio.run(
                    bind_routes(setup, HostBridge(request["url"], Path(request["token_file"])))
                )
                if action == "bind"
                else None
            )
            if result is None:
                raise ValueError("Unknown action")
        print(json.dumps({"ok": True, "result": result}))
    except Exception:
        print('{"ok":false,"error":"Native Hermes configuration or binding failed"}')
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
