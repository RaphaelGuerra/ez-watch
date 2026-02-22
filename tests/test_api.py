from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings


def _write_zones(path: Path, overnight: bool = False) -> None:
    if overnight:
        window = """
        - days: [mon, tue, wed, thu, fri, sat, sun]
          start: \"18:00\"
          end: \"06:00\"
"""
    else:
        window = """
        - days: [mon, tue, wed, thu, fri, sat, sun]
          start: \"00:00\"
          end: \"23:59\"
"""

    path.write_text(
        f"""
zones:
  - zone_id: almoxarifado
    site_id: resort-a
    camera_ids: [\"cam-001\"]
    severity: high
    active_schedule:
      timezone: America/Sao_Paulo
      windows:
{window}
    alert_destinations: [\"whatsapp\", \"email\"]
    suppression_window_sec: 60
    dedupe_window_sec: 30
""",
        encoding="utf-8",
    )


def _settings(tmp_path: Path, zones_file: Path, email_enabled: bool = False) -> Settings:
    return Settings(
        zone_config_path=str(zones_file),
        db_path=str(tmp_path / "test.db"),
        whatsapp_enabled=True,
        whatsapp_webhook_url="https://example.test/webhook",
        email_enabled=email_enabled,
        smtp_host="smtp.local",
        smtp_port=1025,
        smtp_starttls=False,
        smtp_from="relay@test.local",
        email_to_csv="sec@test.local",
        camera_health_enabled=False,
    )


def _event_payload(ts: str = "2026-02-22T15:10:00Z") -> dict:
    return {
        "vendor": "intelbras",
        "event_type": "intrusion",
        "camera_id": "cam-001",
        "camera_name": "Almox Entrance",
        "zone_id": "almoxarifado",
        "timestamp_utc": ts,
        "confidence": 0.92,
        "media_url": "https://nvr.local/clip/abc",
        "raw_payload": {"source": "defense-ia"},
    }


def test_event_sent_success(tmp_path: Path):
    zones_file = tmp_path / "zones.yaml"
    _write_zones(zones_file)
    app = create_app(_settings(tmp_path, zones_file))

    app.state.relay.whatsapp_client.send = lambda _text, _payload: (True, None)

    with TestClient(app) as client:
        response = client.post("/v1/events/cv", json=_event_payload())

    assert response.status_code == 200
    assert response.json()["status"] == "sent"


def test_dedupe_suppression(tmp_path: Path):
    zones_file = tmp_path / "zones.yaml"
    _write_zones(zones_file)
    app = create_app(_settings(tmp_path, zones_file))

    app.state.relay.whatsapp_client.send = lambda _text, _payload: (True, None)

    with TestClient(app) as client:
        first = client.post("/v1/events/cv", json=_event_payload())
        second = client.post("/v1/events/cv", json=_event_payload())

    assert first.status_code == 200
    assert first.json()["status"] == "sent"
    assert second.status_code == 200
    assert second.json()["status"] == "suppressed"
    assert second.json()["reason"] == "dedupe_window"


def test_outside_schedule_suppressed(tmp_path: Path):
    zones_file = tmp_path / "zones.yaml"
    zones_file.write_text(
        """
zones:
  - zone_id: almoxarifado
    site_id: resort-a
    camera_ids: ["cam-001"]
    severity: high
    active_schedule:
      timezone: America/Sao_Paulo
      windows:
        - days: [mon]
          start: "00:00"
          end: "00:10"
    alert_destinations: ["whatsapp"]
    suppression_window_sec: 60
    dedupe_window_sec: 30
""",
        encoding="utf-8",
    )

    app = create_app(_settings(tmp_path, zones_file))
    app.state.relay.whatsapp_client.send = lambda _text, _payload: (True, None)

    with TestClient(app) as client:
        response = client.post("/v1/events/cv", json=_event_payload(ts="2026-02-22T12:00:00Z"))

    assert response.status_code == 200
    assert response.json()["status"] == "suppressed"
    assert response.json()["reason"] == "outside_active_schedule"


def test_email_fallback_when_whatsapp_fails(tmp_path: Path):
    zones_file = tmp_path / "zones.yaml"
    _write_zones(zones_file)
    app = create_app(_settings(tmp_path, zones_file, email_enabled=True))

    app.state.relay.whatsapp_client.send = lambda _text, _payload: (False, "provider_error")
    app.state.relay.email_client.send = lambda recipients, subject, body: (True, None)

    with TestClient(app) as client:
        response = client.post("/v1/events/cv", json=_event_payload())

    assert response.status_code == 200
    assert response.json()["status"] == "sent"
