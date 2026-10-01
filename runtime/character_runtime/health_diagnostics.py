"""Bounded health diagnostics contain no exception messages or private values.

有界健康诊断不包含异常正文或私人值。
"""

from collections.abc import Iterator
from contextlib import contextmanager

STAGES = frozenset(
    {
        "health.import",
        "health.storage-open",
        "health.snapshot",
        "health.stdio-spawn",
        "health.mcp-initialize",
        "health.list-tools",
        "health.protocol-check",
        "health.storage-check",
        "health.stdio-teardown",
    }
)
ERROR_TYPES = frozenset(
    {
        "Exception",
        "ExceptionGroup",
        "FileNotFoundError",
        "ModuleNotFoundError",
        "ImportError",
        "PermissionError",
        "OSError",
        "RuntimeError",
        "ValueError",
        "AssertionError",
        "TimeoutError",
        "UnicodeEncodeError",
        "UnicodeDecodeError",
        "OperationalError",
        "IntegrityError",
        "McpError",
        "BrokenResourceError",
        "EndOfStream",
        "ConnectionError",
    }
)


class HealthFailure(RuntimeError):
    """Expose allowlisted metadata only; never serialize the original exception.
    只暴露白名单元数据，绝不序列化原异常。
    """

    stage: str
    exception_type: str

    def __init__(self, stage: str, error: Exception) -> None:
        self.stage = stage if stage in STAGES else "health.import"
        while isinstance(error, ExceptionGroup) and len(error.exceptions) == 1:
            error = error.exceptions[0]
        if isinstance(error, HealthFailure):
            self.stage = error.stage
            name = error.exception_type
        else:
            name = type(error).__name__
        self.exception_type = name if name in ERROR_TYPES else "Exception"
        super().__init__(self.stage + ": " + self.exception_type)

    def envelope(self) -> dict[str, str | bool]:
        """Return only fixed keys and safe labels. / 仅返回固定键与安全标签。"""
        return {"ok": False, "stage": self.stage, "exception_type": self.exception_type}


@contextmanager
def health_stage(name: str) -> Iterator[None]:
    """Preserve the first failed stage through nested cleanup.
    穿过嵌套清理时保留最初失败阶段。
    """
    if name not in STAGES:
        raise ValueError("Unknown health stage")
    try:
        yield
    except HealthFailure:
        raise
    except Exception as error:
        raise HealthFailure(name, error) from None
