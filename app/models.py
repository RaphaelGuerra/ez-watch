from __future__ import annotations

from datetime import datetime, time
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class VendorType(str, Enum):
    INTELBRAS = "intelbras"
    HIKVISION = "hikvision"


class EventType(str, Enum):
    INTRUSION = "intrusion"
    LINE_CROSS = "line_cross"
    REGION_ENTRY = "region_entry"
    LOITERING = "loitering"
    FACE_MATCH = "face_match"
    CAMERA_DISCONNECT = "camera_disconnect"


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class DayOfWeek(str, Enum):
    MON = "mon"
    TUE = "tue"
    WED = "wed"
    THU = "thu"
    FRI = "fri"
    SAT = "sat"
    SUN = "sun"


class ScheduleWindow(BaseModel):
    days: list[DayOfWeek] = Field(min_length=1)
    start: str = Field(pattern=r"^([01]\d|2[0-3]):([0-5]\d)$")
    end: str = Field(pattern=r"^([01]\d|2[0-3]):([0-5]\d)$")

    def _parse_time(self, value: str) -> time:
        hour, minute = value.split(":")
        return time(hour=int(hour), minute=int(minute))

    def contains(self, local_dt: datetime) -> bool:
        weekday = [
            DayOfWeek.MON,
            DayOfWeek.TUE,
            DayOfWeek.WED,
            DayOfWeek.THU,
            DayOfWeek.FRI,
            DayOfWeek.SAT,
            DayOfWeek.SUN,
        ][local_dt.weekday()]

        if weekday not in self.days:
            return False

        start_time = self._parse_time(self.start)
        end_time = self._parse_time(self.end)
        current = local_dt.time()

        if start_time <= end_time:
            return start_time <= current <= end_time

        return current >= start_time or current <= end_time


class ActiveSchedule(BaseModel):
    timezone: str = "America/Sao_Paulo"
    windows: list[ScheduleWindow] = Field(default_factory=list)

    def is_active(self, local_dt: datetime) -> bool:
        if not self.windows:
            return True
        return any(window.contains(local_dt) for window in self.windows)


class ZoneConfig(BaseModel):
    zone_id: str
    site_id: str
    camera_ids: list[str] = Field(min_length=1)
    severity: Severity = Severity.MEDIUM
    active_schedule: ActiveSchedule = Field(default_factory=ActiveSchedule)
    alert_destinations: list[str] = Field(default_factory=lambda: ["whatsapp"])
    suppression_window_sec: int = Field(default=60, ge=0)
    dedupe_window_sec: int = Field(default=30, ge=0)


class CVEventIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vendor: VendorType
    event_type: EventType
    camera_id: str
    camera_name: str
    zone_id: str
    timestamp_utc: datetime
    confidence: float | None = Field(default=None, ge=0, le=1)
    media_url: str | None = None
    raw_payload: dict[str, Any] = Field(default_factory=dict)


class CameraPing(BaseModel):
    camera_id: str
    timestamp_utc: datetime | None = None


class AlertMessage(BaseModel):
    title: str
    site: str
    zone: str
    camera: str
    local_time: str
    event_type: str
    severity: Severity
    confidence_text: str
    action_link: str | None = None
    shift: str


class ProcessResponse(BaseModel):
    status: str
    reason: str | None = None
    event_id: str
