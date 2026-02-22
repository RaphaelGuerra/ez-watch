from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.responses import Response

EVENTS_RECEIVED = Counter("cv_events_received_total", "Total CV events received", ["vendor", "event_type"])
EVENTS_SUPPRESSED = Counter("cv_events_suppressed_total", "Total CV events suppressed", ["reason"])
ALERTS_SENT = Counter("cv_alerts_sent_total", "Total alerts sent", ["channel", "status"])
PROCESSING_LATENCY = Histogram("cv_event_processing_seconds", "Event processing latency")
HEALTH_ALERTS = Counter("cv_camera_health_alerts_total", "Camera offline alerts triggered")


def metrics_response() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
