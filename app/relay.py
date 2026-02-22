from __future__ import annotations

import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.channels import EmailClient, WhatsAppClient
from app.metrics import EVENTS_SUPPRESSED, PROCESSING_LATENCY
from app.models import AlertMessage, CVEventIn, EventType, ProcessResponse, Severity, ZoneConfig
from app.settings import Settings
from app.store import EventStore, utcnow
from app.zones import ZoneRegistry

logger = logging.getLogger(__name__)

UTC = timezone.utc


class AlertRelay:
    def __init__(
        self,
        settings: Settings,
        store: EventStore,
        zones: ZoneRegistry,
        whatsapp_client: WhatsAppClient | None,
        email_client: EmailClient | None,
    ):
        self.settings = settings
        self.store = store
        self.zones = zones
        self.whatsapp_client = whatsapp_client
        self.email_client = email_client
        self._events_processed = 0

    def process_event(self, event: CVEventIn) -> ProcessResponse:
        started_at = utcnow()
        event_id = self.store.save_event(event, decision="processing", reason=None)

        zone = self.zones.get_zone(event.zone_id)
        if zone is None:
            self.store.update_event_decision(event_id, "rejected", "unknown_zone")
            return ProcessResponse(status="rejected", reason="unknown_zone", event_id=event_id)

        if event.camera_id not in zone.camera_ids:
            self.store.update_event_decision(event_id, "rejected", "camera_not_mapped_to_zone")
            return ProcessResponse(status="rejected", reason="camera_not_mapped_to_zone", event_id=event_id)

        local_dt = self._to_local_dt(event.timestamp_utc, zone)
        if not zone.active_schedule.is_active(local_dt):
            self.store.update_event_decision(event_id, "suppressed", "outside_active_schedule")
            EVENTS_SUPPRESSED.labels(reason="outside_active_schedule").inc()
            self._post_process(started_at)
            return ProcessResponse(status="suppressed", reason="outside_active_schedule", event_id=event_id)

        dedupe_status = self._dedupe_gate(event, zone)
        if dedupe_status is not None:
            self.store.update_event_decision(event_id, "suppressed", dedupe_status)
            EVENTS_SUPPRESSED.labels(reason=dedupe_status).inc()
            self._post_process(started_at)
            return ProcessResponse(status="suppressed", reason=dedupe_status, event_id=event_id)

        alert_message = self._build_alert_message(event, zone, local_dt)
        sent, reason = self._dispatch_event_alert(event_id=event_id, zone=zone, message=alert_message)
        if sent:
            self.store.update_event_decision(event_id, "sent", None)
            now = utcnow()
            self.store.set_last_sent_at(self._dedupe_key(event, zone), now)
            self.store.set_last_sent_at(self._suppression_key(event, zone), now)
            self._post_process(started_at)
            return ProcessResponse(status="sent", reason=None, event_id=event_id)

        self.store.update_event_decision(event_id, "failed", reason)
        self._post_process(started_at)
        return ProcessResponse(status="failed", reason=reason, event_id=event_id)

    def send_camera_offline_alert(self, camera_id: str, last_seen_utc: datetime) -> bool:
        zone = self.zones.zone_for_camera(camera_id)
        zone_id = zone.zone_id if zone else "unknown"
        site_id = zone.site_id if zone else "unknown"
        local_dt = self._to_local_dt(last_seen_utc, zone)
        message = AlertMessage(
            title="Camera offline",
            site=site_id,
            zone=zone_id,
            camera=camera_id,
            local_time=local_dt.strftime("%Y-%m-%d %H:%M:%S %Z"),
            event_type=EventType.CAMERA_DISCONNECT.value,
            severity=(zone.severity if zone else Severity.HIGH),
            confidence_text="n/a",
            action_link=None,
            shift=self._shift_name(local_dt),
        )
        sent, reason = self._dispatch_event_alert(event_id=None, zone=zone, message=message)
        if not sent:
            logger.warning(
                "camera_offline_alert_failed",
                extra={"camera_id": camera_id, "status": reason},
            )
        return sent

    def _dispatch_event_alert(
        self,
        event_id: str | None,
        zone: ZoneConfig | None,
        message: AlertMessage,
    ) -> tuple[bool, str | None]:
        payload = message.model_dump(mode="json")
        text = self._render_message_text(message)
        destinations = zone.alert_destinations if zone else ["whatsapp", "email"]

        sent_whatsapp = False
        whatsapp_error: str | None = None

        if "whatsapp" in destinations and self.whatsapp_client is not None:
            sent_whatsapp, whatsapp_error = self.whatsapp_client.send(text, payload)
            self.store.save_alert(
                event_id=event_id,
                channel="whatsapp",
                destination="webhook",
                status="success" if sent_whatsapp else "failed",
                error=whatsapp_error,
                message_payload=payload,
            )
            if sent_whatsapp:
                return True, None

        if self.email_client is not None and self.settings.email_recipients:
            email_body = text
            email_subject = f"[EZ-WATCH] {message.title} - {message.zone}"
            sent_email, email_error = self.email_client.send(
                recipients=self.settings.email_recipients,
                subject=email_subject,
                body=email_body,
            )
            self.store.save_alert(
                event_id=event_id,
                channel="email",
                destination=",".join(self.settings.email_recipients),
                status="success" if sent_email else "failed",
                error=email_error,
                message_payload=payload,
            )
            if sent_email:
                return True, None
            return False, email_error or whatsapp_error

        return False, whatsapp_error or "no_delivery_channel_configured"

    def _dedupe_gate(self, event: CVEventIn, zone: ZoneConfig) -> str | None:
        now = utcnow()

        if zone.dedupe_window_sec > 0:
            last_dedupe = self.store.get_last_sent_at(self._dedupe_key(event, zone))
            if last_dedupe:
                delta = (now - last_dedupe).total_seconds()
                if delta < zone.dedupe_window_sec:
                    return "dedupe_window"

        if zone.suppression_window_sec > 0:
            last_suppression = self.store.get_last_sent_at(self._suppression_key(event, zone))
            if last_suppression:
                delta = (now - last_suppression).total_seconds()
                if delta < zone.suppression_window_sec:
                    return "suppression_window"

        return None

    def _build_alert_message(self, event: CVEventIn, zone: ZoneConfig, local_dt: datetime) -> AlertMessage:
        confidence_text = "n/a" if event.confidence is None else f"{event.confidence * 100:.0f}%"
        title = f"{event.event_type.value.replace('_', ' ').title()} detected"

        return AlertMessage(
            title=title,
            site=zone.site_id,
            zone=zone.zone_id,
            camera=event.camera_name,
            local_time=local_dt.strftime("%Y-%m-%d %H:%M:%S %Z"),
            event_type=event.event_type.value,
            severity=zone.severity,
            confidence_text=confidence_text,
            action_link=event.media_url,
            shift=self._shift_name(local_dt),
        )

    def _render_message_text(self, message: AlertMessage) -> str:
        lines = [
            f"[EZ-WATCH] {message.title}",
            f"Site: {message.site}",
            f"Zone: {message.zone}",
            f"Camera: {message.camera}",
            f"Time: {message.local_time}",
            f"Event: {message.event_type}",
            f"Severity: {message.severity}",
            f"Confidence: {message.confidence_text}",
            f"Shift: {message.shift}",
        ]
        if message.action_link:
            lines.append(f"Media: {message.action_link}")
        return "\n".join(lines)

    def _dedupe_key(self, event: CVEventIn, zone: ZoneConfig) -> str:
        return f"dedupe:{zone.zone_id}:{event.camera_id}:{event.event_type.value}"

    def _suppression_key(self, event: CVEventIn, zone: ZoneConfig) -> str:
        return f"suppress:{zone.zone_id}:{event.camera_id}"

    def _to_local_dt(self, dt_utc: datetime, zone: ZoneConfig | None) -> datetime:
        tz_name = self.settings.default_timezone
        if zone is not None:
            tz_name = zone.active_schedule.timezone or tz_name

        try:
            tz = ZoneInfo(tz_name)
        except ZoneInfoNotFoundError:
            tz = ZoneInfo(self.settings.default_timezone)

        return dt_utc.astimezone(tz)

    def _shift_name(self, local_dt: datetime) -> str:
        hour = local_dt.hour
        if 6 <= hour < 14:
            return "morning"
        if 14 <= hour < 22:
            return "afternoon"
        return "night"

    def _post_process(self, started_at: datetime) -> None:
        self._events_processed += 1
        PROCESSING_LATENCY.observe((utcnow() - started_at).total_seconds())
        if self._events_processed % self.settings.cleanup_interval_events == 0:
            self.store.cleanup_old_records(self.settings.retention_days)
