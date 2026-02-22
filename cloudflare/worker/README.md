# Cloudflare Workers Deployment (Pure Worker + Durable Object)

This setup runs the alert relay directly in a Cloudflare Worker backed by a Durable Object.
No Docker or Cloudflare Containers is required.

## Requirements

- Node.js 20+
- Wrangler authenticated (`npx wrangler login`)

## Deploy

From project root:

```bash
npm install
```

Set required secrets (Pushover):

```bash
npx wrangler secret put PUSHOVER_APP_TOKEN
npx wrangler secret put PUSHOVER_USER_KEY
```

Optional secrets:

```bash
# optional: set PUSHOVER_TIMEOUT_MS in wrangler.toml
```

Deploy Worker:

```bash
npm run cf:deploy
```

## Endpoints

After deploy, use your Worker URL:

- `https://<worker>.workers.dev/health/live`
- `https://<worker>.workers.dev/health/ready`
- `https://<worker>.workers.dev/v1/zones`
- `https://<worker>.workers.dev/v1/events/cv`
- `https://<worker>.workers.dev/metrics`

## Notes

- Zone configuration is read from `ZONE_CONFIG_JSON` in `wrangler.toml`.
- The Python/FastAPI and Docker files in repo are legacy reference/rollback assets.
- Route a custom domain from Cloudflare dashboard if needed.
