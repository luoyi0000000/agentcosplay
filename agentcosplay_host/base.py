"""Strict shared wire primitives. / 严格的共享传输基础类型。"""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

Text = Annotated[str, Field(min_length=1, max_length=4000)]

Identifier = Annotated[str, Field(min_length=1, max_length=200)]


class Model(BaseModel):
    """Reject unknown fields by default and validate assignments at contract boundaries.

    默认拒绝未知字段，并在契约边界验证赋值。
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True, allow_inf_nan=False)
