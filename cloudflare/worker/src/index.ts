import { Container } from "@cloudflare/containers";
import { env } from "cloudflare:workers";

export class AlertRelayContainer extends Container {
  defaultPort = 8000;
  sleepAfter = "10m";

  // Pass Worker vars/secrets into the FastAPI container runtime.
  envVars = {
    APP_ENV: env.APP_ENV,
    LISTEN_HOST: env.LISTEN_HOST,
    LISTEN_PORT: env.LISTEN_PORT,
    ZONE_CONFIG_PATH: env.ZONE_CONFIG_PATH,
    DB_PATH: env.DB_PATH,
    RETENTION_DAYS: env.RETENTION_DAYS,
    CLEANUP_INTERVAL_EVENTS: env.CLEANUP_INTERVAL_EVENTS,
    DEFAULT_TIMEZONE: env.DEFAULT_TIMEZONE,
    WHATSAPP_ENABLED: env.WHATSAPP_ENABLED,
    WHATSAPP_WEBHOOK_URL: env.WHATSAPP_WEBHOOK_URL,
    WHATSAPP_TIMEOUT_SEC: env.WHATSAPP_TIMEOUT_SEC,
    WHATSAPP_BEARER_TOKEN: env.WHATSAPP_BEARER_TOKEN,
    EMAIL_ENABLED: env.EMAIL_ENABLED,
    SMTP_HOST: env.SMTP_HOST,
    SMTP_PORT: env.SMTP_PORT,
    SMTP_USERNAME: env.SMTP_USERNAME,
    SMTP_PASSWORD: env.SMTP_PASSWORD,
    SMTP_STARTTLS: env.SMTP_STARTTLS,
    SMTP_FROM: env.SMTP_FROM,
    EMAIL_TO_CSV: env.EMAIL_TO_CSV,
    CAMERA_HEALTH_ENABLED: env.CAMERA_HEALTH_ENABLED,
    CAMERA_OFFLINE_THRESHOLD_SEC: env.CAMERA_OFFLINE_THRESHOLD_SEC,
    CAMERA_HEALTH_CHECK_INTERVAL_SEC: env.CAMERA_HEALTH_CHECK_INTERVAL_SEC,
    CAMERA_OFFLINE_ALERT_COOLDOWN_SEC: env.CAMERA_OFFLINE_ALERT_COOLDOWN_SEC,
  } as Record<string, string | undefined>;

  override onStart() {
    console.log("alert_relay_container_started");
  }

  override onError(error: unknown) {
    console.error("alert_relay_container_error", error);
  }
}

export default {
  async fetch(request: Request, envBinding: Env): Promise<Response> {
    const url = new URL(request.url);

    // Single default container instance. Add ?instance=<name> to shard by resort/site.
    const instanceName = url.searchParams.get("instance") || "default";

    const container = envBinding.ALERT_RELAY.getByName(instanceName);
    return container.fetch(request);
  },
};

interface Env {
  ALERT_RELAY: DurableObjectNamespace;
}
