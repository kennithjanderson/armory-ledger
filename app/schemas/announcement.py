from datetime import timezone
import re
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator


class AnnouncementRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1, max_length=5000)
    severity: Literal["info", "success", "warning", "danger"] = "info"
    enabled: bool = True
    starts_at: AwareDatetime
    ends_at: AwareDatetime

    @field_validator("starts_at", "ends_at", mode="before")
    @classmethod
    def reject_numeric_timestamp(cls, value):
        if isinstance(value, (int, float, bool)):
            raise ValueError("Use an ISO 8601 timestamp with Z or an explicit UTC offset.")
        if isinstance(value, str) and not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})",
            value,
        ):
            raise ValueError("Use an ISO 8601 timestamp with Z or an explicit UTC offset.")
        return value

    @field_validator("starts_at", "ends_at")
    @classmethod
    def normalize_utc(cls, value):
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def validate_window(self):
        if self.ends_at <= self.starts_at:
            raise ValueError("End time must be later than start time.")
        return self
