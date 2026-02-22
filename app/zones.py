from __future__ import annotations

from pathlib import Path

import yaml

from app.models import ZoneConfig


class ZoneRegistry:
    def __init__(self, zones: list[ZoneConfig]):
        self._zones = {zone.zone_id: zone for zone in zones}
        self._camera_index: dict[str, str] = {}
        for zone in zones:
            for camera_id in zone.camera_ids:
                self._camera_index[camera_id] = zone.zone_id

    @classmethod
    def from_yaml(cls, path: str) -> "ZoneRegistry":
        config_path = Path(path)
        if not config_path.exists():
            raise FileNotFoundError(f"Zone config not found: {config_path}")

        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        if not raw:
            return cls(zones=[])

        zones_data = raw.get("zones", [])
        zones = [ZoneConfig.model_validate(item) for item in zones_data]
        return cls(zones=zones)

    def get_zone(self, zone_id: str) -> ZoneConfig | None:
        return self._zones.get(zone_id)

    def zone_for_camera(self, camera_id: str) -> ZoneConfig | None:
        zone_id = self._camera_index.get(camera_id)
        if zone_id is None:
            return None
        return self._zones.get(zone_id)

    @property
    def zones(self) -> list[ZoneConfig]:
        return list(self._zones.values())
