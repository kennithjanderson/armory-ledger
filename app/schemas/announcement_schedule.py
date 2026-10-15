"""Wall-clock scheduling with explicit DST occurrence selection; no DB access."""
from datetime import datetime, timezone
import re
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, field_validator


def aware_instant(value):
    if isinstance(value, str):
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:\d{2})", value):
            raise ValueError("Use an ISO 8601 timestamp with Z or an explicit UTC offset.")
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Use an ISO 8601 timestamp with Z or an explicit UTC offset.")
    return value.astimezone(timezone.utc)


class LocalSchedule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timezone: str
    local_time: str
    occurrence: Literal["earlier", "later"] | None = None

    @field_validator("timezone")
    @classmethod
    def valid_zone(cls, value):
        try:
            ZoneInfo(value)
        except (ValueError, ZoneInfoNotFoundError):
            raise ValueError("Choose a valid IANA timezone, such as America/Chicago or UTC.")
        return value

    @field_validator("local_time")
    @classmethod
    def valid_local(cls, value):
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?", value):
            raise ValueError("Enter a local date and time without a UTC offset.")
        datetime.fromisoformat(value)
        return value

    def preview(self):
        wall = datetime.fromisoformat(self.local_time)
        zone = ZoneInfo(self.timezone)
        candidates = set()
        for fold in (0, 1):
            utc = wall.replace(tzinfo=zone, fold=fold).astimezone(timezone.utc)
            if utc.astimezone(zone).replace(tzinfo=None) == wall:
                candidates.add(utc)
        if not candidates:
            raise ValueError("This local time does not exist because the clocks move forward. Choose another time.")
        options = []
        for index, instant in enumerate(sorted(candidates)):
            local = instant.astimezone(zone)
            options.append({
                "occurrence": "earlier" if index == 0 else "later",
                "utc": instant.isoformat(),
                "label": f"{local.tzname()} (UTC{local.strftime('%z')}) — {instant.strftime('%Y-%m-%d %H:%M')} UTC",
            })
        selected = options[0] if len(options) == 1 else next(
            (item for item in options if item["occurrence"] == self.occurrence), None,
        )
        return {"local_time": self.local_time, "options": options,
                "utc": selected["utc"] if selected else None}

    def instant(self):
        result = self.preview()
        if result["utc"] is None:
            raise ValueError("This local time occurs twice. Choose the earlier or later occurrence.")
        return aware_instant(result["utc"])


class SchedulePreview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timezone: str
    local_time: str | None = None
    occurrence: Literal["earlier", "later"] | None = None
    instant: str | None = None

    def preview(self):
        if (self.instant is None) == (self.local_time is None):
            raise ValueError("Provide either an instant or a local time.")
        if self.instant is None:
            return LocalSchedule(timezone=self.timezone, local_time=self.local_time,
                                 occurrence=self.occurrence).preview()
        # Validate the zone before conversion, including path-like identifiers.
        LocalSchedule(timezone=self.timezone, local_time="2000-01-01T00:00")
        instant = aware_instant(self.instant)
        local = instant.astimezone(ZoneInfo(self.timezone))
        return LocalSchedule(timezone=self.timezone,
                             local_time=local.replace(tzinfo=None).isoformat(),
                             occurrence="later" if local.fold else "earlier").preview()
