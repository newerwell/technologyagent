"""P07 显式偏好 API 契约。"""

from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field


class RememberPreferenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    key: Literal["default_warehouse", "preferred_supplier", "max_lead_days"]
    value: Any
    remember: Literal[True]


class PreferenceValue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    key: str
    value: Any
    explicit: bool = True
