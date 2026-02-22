type VendorType = "intelbras" | "hikvision";
type EventType = "intrusion" | "line_cross" | "region_entry" | "loitering" | "face_match" | "camera_disconnect";
type Severity = "low" | "medium" | "high";
type DayOfWeek = "mon" | "tue" | "wed" | "thu" | "fri" | "sat" | "sun";

type ScheduleWindow = {
  days: DayOfWeek[];
  start: string;
  end: string;
};

type ActiveSchedule = {
  timezone?: string;
  windows?: ScheduleWindow[];
};

type ZoneConfig = {
  zone_id: string;
  site_id: string;
  camera_ids: string[];
  severity: Severity;
  active_schedule: ActiveSchedule;
  alert_destinations: string[];
  suppression_window_sec: number;
  dedupe_window_sec: number;
};

type ZoneConfigPayload = {
  zones: ZoneConfig[];
};

type CVEventIn = {
  vendor: VendorType;
  event_type: EventType;
  camera_id: string;
  camera_name: string;
  zone_id: string;
  timestamp_utc: string;
  confidence?: number | null;
  media_url?: string | null;
  raw_payload?: Record<string, unknown>;
};

type CameraPing = {
  camera_id: string;
  timestamp_utc?: string;
};

const EVENT_TYPES = new Set<EventType>([
  "intrusion",
  "line_cross",
  "region_entry",
  "loitering",
  "face_match",
  "camera_disconnect",
]);

const VENDORS = new Set<VendorType>(["intelbras", "hikvision"]);

const WEEKDAY_INDEX: DayOfWeek[] = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"];

const METRIC_EVENTS_RECEIVED = "metric:events_received:";
const METRIC_EVENTS_SUPPRESSED = "metric:events_suppressed:";
const METRIC_ALERTS_SENT = "metric:alerts_sent:pushover:";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function parseHourMinute(value: string): number | null {
  const match = /^(?:[01]\d|2[0-3]):[0-5]\d$/.exec(value);
  if (!match) {
    return null;
  }
  const [hourStr, minuteStr] = value.split(":");
  const hour = Number.parseInt(hourStr, 10);
  const minute = Number.parseInt(minuteStr, 10);
  return hour * 60 + minute;
}

function localDayAndMinutes(utcDate: Date, timezone: string): { day: DayOfWeek; minutes: number } {
  const formatter = new Intl.DateTimeFormat("en-US", {
    timeZone: timezone,
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  });

  const parts = formatter.formatToParts(utcDate);
  const weekdayPart = parts.find((part) => part.type === "weekday")?.value.toLowerCase() ?? "sun";
  const hourPart = parts.find((part) => part.type === "hour")?.value ?? "0";
  const minutePart = parts.find((part) => part.type === "minute")?.value ?? "0";

  const dayShort = weekdayPart.slice(0, 3) as DayOfWeek;
  const hour = Number.parseInt(hourPart, 10);
  const minute = Number.parseInt(minutePart, 10);

  return {
    day: WEEKDAY_INDEX.includes(dayShort) ? dayShort : "sun",
    minutes: hour * 60 + minute,
  };
}

function isActiveSchedule(schedule: ActiveSchedule, utcDate: Date, defaultTimezone: string): boolean {
  const timezone = schedule.timezone || defaultTimezone;
  const windows = schedule.windows ?? [];

  if (windows.length === 0) {
    return true;
  }

  let local: { day: DayOfWeek; minutes: number };
  try {
    local = localDayAndMinutes(utcDate, timezone);
  } catch {
    local = localDayAndMinutes(utcDate, defaultTimezone);
  }

  for (const window of windows) {
    if (!window.days.includes(local.day)) {
      continue;
    }

    const start = parseHourMinute(window.start);
    const end = parseHourMinute(window.end);
    if (start === null || end === null) {
      continue;
    }

    if (start <= end) {
      if (local.minutes >= start && local.minutes <= end) {
        return true;
      }
    } else {
      if (local.minutes >= start || local.minutes <= end) {
        return true;
      }
    }
  }

  return false;
}

function formatLocalTime(utcDate: Date, timezone: string, fallbackTimezone: string): string {
  const format = (tz: string) => {
    const formatter = new Intl.DateTimeFormat("en-CA", {
      timeZone: tz,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hourCycle: "h23",
      timeZoneName: "short",
    });

    return formatter.format(utcDate).replace(",", "");
  };

  try {
    return format(timezone);
  } catch {
    return format(fallbackTimezone);
  }
}

function shiftName(utcDate: Date, timezone: string, fallbackTimezone: string): string {
  const formatter = new Intl.DateTimeFormat("en-US", {
    timeZone: timezone || fallbackTimezone,
    hour: "2-digit",
    hourCycle: "h23",
  });

  let hour = 0;
  try {
    const hourPart = formatter.formatToParts(utcDate).find((part) => part.type === "hour")?.value ?? "0";
    hour = Number.parseInt(hourPart, 10);
  } catch {
    const fallbackFormatter = new Intl.DateTimeFormat("en-US", {
      timeZone: fallbackTimezone,
      hour: "2-digit",
      hourCycle: "h23",
    });
    const hourPart = fallbackFormatter.formatToParts(utcDate).find((part) => part.type === "hour")?.value ?? "0";
    hour = Number.parseInt(hourPart, 10);
  }

  if (hour >= 6 && hour < 14) {
    return "morning";
  }
  if (hour >= 14 && hour < 22) {
    return "afternoon";
  }
  return "night";
}

function metricLabelEscape(value: string): string {
  return value.replaceAll("\\", "\\\\").replaceAll('"', '\\"');
}

function toPrometheusLine(name: string, labels: Record<string, string>, value: number): string {
  const labelEntries = Object.entries(labels);
  if (labelEntries.length === 0) {
    return `${name} ${value}`;
  }

  const labelText = labelEntries
    .map(([key, item]) => `${key}="${metricLabelEscape(item)}"`)
    .join(",");

  return `${name}{${labelText}} ${value}`;
}

export class AlertRelayContainer implements DurableObject {
  private readonly state: DurableObjectState;
  private readonly env: Env;
  private zonesCache: ZoneConfigPayload | null = null;

  constructor(state: DurableObjectState, env: Env) {
    this.state = state;
    this.env = env;
  }

  async fetch(request: Request): Promise<Response> {
    const url = new URL(request.url);

    if (request.method === "GET" && url.pathname === "/health/live") {
      return jsonResponse(200, { status: "ok" });
    }

    if (request.method === "GET" && url.pathname === "/health/ready") {
      const zones = this.loadZones();
      if (!zones) {
        return jsonResponse(500, { detail: "invalid_zone_config" });
      }
      return jsonResponse(200, { status: "ok", zones_loaded: zones.zones.length });
    }

    if (request.method === "GET" && url.pathname === "/v1/zones") {
      const zones = this.loadZones();
      if (!zones) {
        return jsonResponse(500, { detail: "invalid_zone_config" });
      }
      return jsonResponse(200, zones);
    }

    if (request.method === "GET" && url.pathname === "/metrics") {
      return this.metricsResponse();
    }

    if (request.method === "POST" && url.pathname === "/v1/health/camera-ping") {
      return this.handleCameraPing(request);
    }

    if (request.method === "POST" && url.pathname === "/v1/events/cv") {
      return this.handleEvent(request);
    }

    return jsonResponse(404, { detail: "not_found" });
  }

  private loadZones(): ZoneConfigPayload | null {
    if (this.zonesCache) {
      return this.zonesCache;
    }

    const raw = this.env.ZONE_CONFIG_JSON;
    if (!raw) {
      return { zones: [] };
    }

    try {
      const parsed = JSON.parse(raw) as ZoneConfigPayload;
      if (!parsed || !Array.isArray(parsed.zones)) {
        return null;
      }

      this.zonesCache = {
        zones: parsed.zones.map((zone) => ({
          zone_id: zone.zone_id,
          site_id: zone.site_id,
          camera_ids: Array.isArray(zone.camera_ids) ? zone.camera_ids : [],
          severity: (zone.severity ?? "medium") as Severity,
          active_schedule: zone.active_schedule ?? { timezone: this.env.DEFAULT_TIMEZONE, windows: [] },
          alert_destinations: Array.isArray(zone.alert_destinations) ? zone.alert_destinations : ["whatsapp"],
          suppression_window_sec: Number.isFinite(zone.suppression_window_sec)
            ? zone.suppression_window_sec
            : 60,
          dedupe_window_sec: Number.isFinite(zone.dedupe_window_sec) ? zone.dedupe_window_sec : 30,
        })),
      };

      void this.state.storage.put("zone_config_cache_version", "v1");
      return this.zonesCache;
    } catch {
      return null;
    }
  }

  private async handleCameraPing(request: Request): Promise<Response> {
    let payload: unknown;
    try {
      payload = await request.json();
    } catch {
      return jsonResponse(400, { detail: "invalid_payload" });
    }

    if (!payload || typeof payload !== "object") {
      return jsonResponse(400, { detail: "invalid_payload" });
    }

    const ping = payload as Partial<CameraPing>;
    if (!ping.camera_id || typeof ping.camera_id !== "string") {
      return jsonResponse(400, { detail: "invalid_payload" });
    }

    const pingDate = ping.timestamp_utc ? new Date(ping.timestamp_utc) : new Date();
    if (Number.isNaN(pingDate.getTime())) {
      return jsonResponse(400, { detail: "invalid_payload" });
    }

    await this.state.storage.put(`heartbeat:${ping.camera_id}`, Math.floor(pingDate.getTime() / 1000));
    return jsonResponse(200, { status: "ok" });
  }

  private async handleEvent(request: Request): Promise<Response> {
    let payload: unknown;
    try {
      payload = await request.json();
    } catch {
      return jsonResponse(400, { detail: "invalid_payload" });
    }

    const parsed = this.validateEvent(payload);
    if (!parsed) {
      return jsonResponse(400, { detail: "invalid_payload" });
    }

    await this.incrementCounter(`${METRIC_EVENTS_RECEIVED}${parsed.vendor}:${parsed.event_type}`);

    const zones = this.loadZones();
    if (!zones) {
      return jsonResponse(500, { detail: "invalid_zone_config" });
    }

    const zone = zones.zones.find((item) => item.zone_id === parsed.zone_id);
    if (!zone) {
      return jsonResponse(400, { detail: "unknown_zone" });
    }

    if (!zone.camera_ids.includes(parsed.camera_id)) {
      return jsonResponse(400, { detail: "camera_not_mapped_to_zone" });
    }

    const eventDate = new Date(parsed.timestamp_utc);
    const defaultTimezone = this.env.DEFAULT_TIMEZONE || "America/Sao_Paulo";

    if (!isActiveSchedule(zone.active_schedule, eventDate, defaultTimezone)) {
      await this.incrementCounter(`${METRIC_EVENTS_SUPPRESSED}outside_active_schedule`);
      return jsonResponse(200, {
        status: "suppressed",
        reason: "outside_active_schedule",
        event_id: crypto.randomUUID(),
      });
    }

    const nowSec = Math.floor(Date.now() / 1000);
    const dedupeKey = `dedupe:${zone.zone_id}:${parsed.camera_id}:${parsed.event_type}`;
    const suppressKey = `suppress:${zone.zone_id}:${parsed.camera_id}`;

    const lastDedupe = (await this.state.storage.get<number>(dedupeKey)) ?? 0;
    if (zone.dedupe_window_sec > 0 && lastDedupe > 0 && nowSec - lastDedupe < zone.dedupe_window_sec) {
      await this.incrementCounter(`${METRIC_EVENTS_SUPPRESSED}dedupe_window`);
      return jsonResponse(200, {
        status: "suppressed",
        reason: "dedupe_window",
        event_id: crypto.randomUUID(),
      });
    }

    const lastSuppress = (await this.state.storage.get<number>(suppressKey)) ?? 0;
    if (zone.suppression_window_sec > 0 && lastSuppress > 0 && nowSec - lastSuppress < zone.suppression_window_sec) {
      await this.incrementCounter(`${METRIC_EVENTS_SUPPRESSED}suppression_window`);
      return jsonResponse(200, {
        status: "suppressed",
        reason: "suppression_window",
        event_id: crypto.randomUUID(),
      });
    }

    const sent = await this.sendPushover(parsed, zone, eventDate, defaultTimezone);
    if (!sent.ok) {
      await this.incrementCounter(`${METRIC_ALERTS_SENT}failed`);
      return jsonResponse(502, { detail: sent.reason });
    }

    const eventId = crypto.randomUUID();
    await this.incrementCounter(`${METRIC_ALERTS_SENT}success`);
    await this.state.storage.put(dedupeKey, nowSec);
    await this.state.storage.put(suppressKey, nowSec);

    return jsonResponse(200, {
      status: "sent",
      reason: null,
      event_id: eventId,
    });
  }

  private validateEvent(payload: unknown): CVEventIn | null {
    if (!payload || typeof payload !== "object") {
      return null;
    }

    const event = payload as Partial<CVEventIn>;
    if (!event.vendor || !VENDORS.has(event.vendor)) {
      return null;
    }
    if (!event.event_type || !EVENT_TYPES.has(event.event_type)) {
      return null;
    }
    if (!event.camera_id || typeof event.camera_id !== "string") {
      return null;
    }
    if (!event.camera_name || typeof event.camera_name !== "string") {
      return null;
    }
    if (!event.zone_id || typeof event.zone_id !== "string") {
      return null;
    }
    if (!event.timestamp_utc || typeof event.timestamp_utc !== "string") {
      return null;
    }

    const parsedDate = new Date(event.timestamp_utc);
    if (Number.isNaN(parsedDate.getTime())) {
      return null;
    }

    if (event.confidence !== undefined && event.confidence !== null) {
      if (typeof event.confidence !== "number" || event.confidence < 0 || event.confidence > 1) {
        return null;
      }
    }

    if (event.media_url !== undefined && event.media_url !== null && typeof event.media_url !== "string") {
      return null;
    }

    if (event.raw_payload !== undefined && (typeof event.raw_payload !== "object" || event.raw_payload === null)) {
      return null;
    }

    return {
      vendor: event.vendor,
      event_type: event.event_type,
      camera_id: event.camera_id,
      camera_name: event.camera_name,
      zone_id: event.zone_id,
      timestamp_utc: event.timestamp_utc,
      confidence: event.confidence ?? null,
      media_url: event.media_url ?? null,
      raw_payload: event.raw_payload ?? {},
    };
  }

  private async sendPushover(
    event: CVEventIn,
    zone: ZoneConfig,
    eventDate: Date,
    defaultTimezone: string,
  ): Promise<{ ok: true } | { ok: false; reason: string }> {
    const allowsPushover =
      zone.alert_destinations.includes("pushover") || zone.alert_destinations.includes("whatsapp");
    if (!allowsPushover) {
      return { ok: false, reason: "no_delivery_channel_configured" };
    }

    if (this.env.PUSHOVER_ENABLED === "false") {
      return { ok: false, reason: "no_delivery_channel_configured" };
    }

    if (!this.env.PUSHOVER_APP_TOKEN || !this.env.PUSHOVER_USER_KEY) {
      return { ok: false, reason: "no_delivery_channel_configured" };
    }

    const timezone = zone.active_schedule?.timezone || defaultTimezone;
    const localTime = formatLocalTime(eventDate, timezone, defaultTimezone);
    const confidenceText =
      event.confidence === null || event.confidence === undefined
        ? "n/a"
        : `${Math.round(event.confidence * 100)}%`;

    const message = {
      title: `${event.event_type.replaceAll("_", " ").replace(/\b\w/g, (s) => s.toUpperCase())} detected`,
      site: zone.site_id,
      zone: zone.zone_id,
      camera: event.camera_name,
      local_time: localTime,
      event_type: event.event_type,
      severity: zone.severity,
      confidence_text: confidenceText,
      action_link: event.media_url ?? null,
      shift: shiftName(eventDate, timezone, defaultTimezone),
    };

    const textLines = [
      `[EZ-WATCH] ${message.title}`,
      `Site: ${message.site}`,
      `Zone: ${message.zone}`,
      `Camera: ${message.camera}`,
      `Time: ${message.local_time}`,
      `Event: ${message.event_type}`,
      `Severity: ${message.severity}`,
      `Confidence: ${message.confidence_text}`,
      `Shift: ${message.shift}`,
    ];

    if (message.action_link) {
      textLines.push(`Media: ${message.action_link}`);
    }

    const timeoutMsRaw = Number.parseInt(this.env.PUSHOVER_TIMEOUT_MS || "8000", 10);
    const timeoutMs = Number.isFinite(timeoutMsRaw) && timeoutMsRaw > 0 ? timeoutMsRaw : 8000;

    const form = new URLSearchParams({
      token: this.env.PUSHOVER_APP_TOKEN,
      user: this.env.PUSHOVER_USER_KEY,
      title: `[EZ-WATCH] ${message.title}`.slice(0, 100),
      message: textLines.join("\n").slice(0, 1024),
      priority: "2",
      retry: "30",
      expire: "600",
      sound: "persistent",
    });

    try {
      const response = await fetch("https://api.pushover.net/1/messages.json", {
        method: "POST",
        body: form,
        signal: AbortSignal.timeout(timeoutMs),
      });

      if (!response.ok) {
        return { ok: false, reason: "pushover_send_failed" };
      }

      return { ok: true };
    } catch (error) {
      if (error instanceof Error && error.name === "TimeoutError") {
        return { ok: false, reason: "pushover_timeout" };
      }
      return { ok: false, reason: "pushover_send_failed" };
    }
  }

  private async incrementCounter(key: string): Promise<void> {
    const current = (await this.state.storage.get<number>(key)) ?? 0;
    await this.state.storage.put(key, current + 1);
  }

  private async metricsResponse(): Promise<Response> {
    const lines: string[] = [
      "# HELP cv_events_received_total Total CV events received",
      "# TYPE cv_events_received_total counter",
    ];

    const received = await this.state.storage.list<number>({ prefix: METRIC_EVENTS_RECEIVED });
    for (const [key, value] of received) {
      const suffix = key.slice(METRIC_EVENTS_RECEIVED.length);
      const [vendor, eventType] = suffix.split(":");
      lines.push(toPrometheusLine("cv_events_received_total", { vendor, event_type: eventType }, value ?? 0));
    }

    lines.push("# HELP cv_events_suppressed_total Total CV events suppressed");
    lines.push("# TYPE cv_events_suppressed_total counter");
    const suppressed = await this.state.storage.list<number>({ prefix: METRIC_EVENTS_SUPPRESSED });
    for (const [key, value] of suppressed) {
      const reason = key.slice(METRIC_EVENTS_SUPPRESSED.length);
      lines.push(toPrometheusLine("cv_events_suppressed_total", { reason }, value ?? 0));
    }

    lines.push("# HELP cv_alerts_sent_total Total alerts sent");
    lines.push("# TYPE cv_alerts_sent_total counter");
    const alerts = await this.state.storage.list<number>({ prefix: METRIC_ALERTS_SENT });
    for (const [key, value] of alerts) {
      const status = key.slice(METRIC_ALERTS_SENT.length);
      lines.push(toPrometheusLine("cv_alerts_sent_total", { channel: "pushover", status }, value ?? 0));
    }

    lines.push("");

    return new Response(lines.join("\n"), {
      status: 200,
      headers: { "content-type": "text/plain; version=0.0.4; charset=utf-8" },
    });
  }
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const objectId = env.ALERT_RELAY.idFromName("default");
    const relay = env.ALERT_RELAY.get(objectId);
    return relay.fetch(request);
  },
};

interface Env {
  ALERT_RELAY: DurableObjectNamespace;
  APP_ENV?: string;
  DEFAULT_TIMEZONE?: string;
  PUSHOVER_ENABLED?: string;
  PUSHOVER_APP_TOKEN?: string;
  PUSHOVER_USER_KEY?: string;
  PUSHOVER_TIMEOUT_MS?: string;
  CAMERA_HEALTH_ENABLED?: string;
  CAMERA_OFFLINE_THRESHOLD_SEC?: string;
  ZONE_CONFIG_JSON?: string;
}
