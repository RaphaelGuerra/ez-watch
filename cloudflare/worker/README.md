# Cloudflare Workers Deployment (Containers)

This setup deploys the existing FastAPI relay container behind a Cloudflare Worker using Cloudflare Containers.

## Requirements

- Cloudflare account on a Workers Paid plan (Containers is beta)
- Node.js 20+
- Docker running locally for `wrangler deploy`
- Wrangler authenticated (`npx wrangler login`)

## Deploy

From project root:

```bash
npm install
```

Set required secrets (minimum WhatsApp webhook):

```bash
npx wrangler secret put WHATSAPP_WEBHOOK_URL
```

Optional secrets:

```bash
npx wrangler secret put WHATSAPP_BEARER_TOKEN
npx wrangler secret put SMTP_HOST
npx wrangler secret put SMTP_USERNAME
npx wrangler secret put SMTP_PASSWORD
```

Deploy Worker + container image:

```bash
npm run cf:deploy
```

Check container rollout state:

```bash
npm run cf:containers:list
npm run cf:containers:images
```

## Endpoints

After deploy, use your Worker URL:

- `https://<worker>.workers.dev/health/live`
- `https://<worker>.workers.dev/v1/events/cv`

## Notes

- First deploy can take several minutes while container infrastructure provisions.
- Route a custom domain from Cloudflare dashboard if needed.
- Use `?instance=<site-id>` to route to separate container instances per resort.
