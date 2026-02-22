from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from app.channels import EmailClient, WhatsAppClient
from app.logging_utils import configure_logging
from app.metrics import EVENTS_RECEIVED, HEALTH_ALERTS, metrics_response
from app.models import CVEventIn, CameraPing, ProcessResponse
from app.relay import AlertRelay
from app.settings import Settings, settings as default_settings
from app.store import EventStore, utcnow
from app.zones import ZoneRegistry

configure_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(camera_health_monitor(app), name="camera-health-monitor")
    app.state.camera_health_task = task
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


async def camera_health_monitor(app: FastAPI) -> None:
    settings: Settings = app.state.settings
    if not settings.camera_health_enabled:
        return

    while True:
        await asyncio.sleep(settings.camera_health_check_interval_sec)
        now = utcnow()
        stale_cameras = app.state.store.get_stale_cameras(settings.camera_offline_threshold_sec, now=now)

        for camera_id, last_seen in stale_cameras:
            last_alert = app.state.store.get_last_health_alert_at(camera_id)
            if last_alert:
                cooldown_elapsed = (now - last_alert).total_seconds()
                if cooldown_elapsed < settings.camera_offline_alert_cooldown_sec:
                    continue

            sent = app.state.relay.send_camera_offline_alert(camera_id=camera_id, last_seen_utc=last_seen)
            if sent:
                app.state.store.set_last_health_alert_at(camera_id, now)
                HEALTH_ALERTS.inc()


def create_app(app_settings: Settings | None = None) -> FastAPI:
    app_settings = app_settings or default_settings

    zones = ZoneRegistry.from_yaml(app_settings.zone_config_path)
    store = EventStore(app_settings.db_path)

    whatsapp_client = None
    if app_settings.whatsapp_enabled and app_settings.whatsapp_webhook_url:
        whatsapp_client = WhatsAppClient(
            webhook_url=app_settings.whatsapp_webhook_url,
            timeout_sec=app_settings.whatsapp_timeout_sec,
            bearer_token=app_settings.whatsapp_bearer_token,
        )

    email_client = None
    if app_settings.email_enabled and app_settings.smtp_host:
        email_client = EmailClient(
            host=app_settings.smtp_host,
            port=app_settings.smtp_port,
            username=app_settings.smtp_username,
            password=app_settings.smtp_password,
            sender=app_settings.smtp_from,
            starttls=app_settings.smtp_starttls,
        )

    relay = AlertRelay(
        settings=app_settings,
        store=store,
        zones=zones,
        whatsapp_client=whatsapp_client,
        email_client=email_client,
    )

    app = FastAPI(title="EZ-WATCH Alert Relay", version="0.1.0", lifespan=lifespan)
    app.state.settings = app_settings
    app.state.zones = zones
    app.state.store = store
    app.state.relay = relay

    @app.get("/health/live")
    def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready")
    def ready() -> dict[str, str | int]:
        return {"status": "ok", "zones_loaded": len(app.state.zones.zones)}

    @app.get("/metrics")
    def metrics():
        return metrics_response()

    @app.get("/v1/zones")
    def list_zones() -> dict[str, list[dict]]:
        payload = [zone.model_dump() for zone in app.state.zones.zones]
        return {"zones": payload}

    @app.post("/v1/health/camera-ping")
    def camera_ping(ping: CameraPing) -> dict[str, str]:
        ping_time = ping.timestamp_utc or utcnow()
        app.state.store.upsert_camera_heartbeat(ping.camera_id, ping_time)
        return {"status": "ok"}

    @app.post("/v1/events/cv", response_model=ProcessResponse)
    def ingest_cv_event(event: CVEventIn) -> ProcessResponse:
        EVENTS_RECEIVED.labels(vendor=event.vendor.value, event_type=event.event_type.value).inc()
        result = app.state.relay.process_event(event)

        logger.info(
            "event_processed",
            extra={
                "event_id": result.event_id,
                "camera_id": event.camera_id,
                "zone_id": event.zone_id,
                "status": result.status,
            },
        )

        if result.status == "rejected":
            raise HTTPException(status_code=400, detail=result.reason)
        if result.status == "failed":
            raise HTTPException(status_code=502, detail=result.reason)
        return result

    return app


app = create_app()
