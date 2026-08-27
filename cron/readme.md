# london-cycles-cron

A Cloudflare Worker whose only job is to fire `workflow_dispatch` on
`.github/workflows/query.yml` every fifteen minutes.

GitHub's own `schedule` trigger is best-effort: it delivers events late and
drops them when they are late enough that the next occurrence has come round.
In practice this repo saw roughly one in nine hourly triggers honoured. This
Worker takes over as the normal path; the `schedule` entry in `query.yml`
remains as a backstop.

There is no HTTP endpoint: `workers_dev = false`, and the `fetch` handler exists
only to return 404 rather than a runtime error. To fire it by hand, use the
Worker's **Trigger scheduled event** in the dashboard, or locally:

```bash
cd cron && npx wrangler dev --test-scheduled
# then, in another shell
curl "http://localhost:8787/__scheduled?cron=*/15+*+*+*+*"
```

## Setup

The GitHub PAT (scope: `repo`, or `actions: write` on a fine-grained token)
lives in the account Secrets Store as `GH_PAT_LONDON_CYCLES_DB` and is bound to
the Worker as `GH_PAT`. Fill `store_id` in `wrangler.toml` with the id from:

```bash
wrangler secrets-store store list --remote
```

## Monitoring

An external scheduler fails silently, so `query.yml` pings a healthchecks.io
check after every successful snapshot and pings `/fail` if the run breaks. One
check covers both failure modes — the Worker not firing, and a run firing but
failing — because either one stops the pings.

Set the repository secret `HEALTHCHECK_URL` to the check's ping URL (no trailing
slash), and configure the check with a period of 15 minutes and a grace of 25,
giving the ~40-minute silence window. The ping is per snapshot rather than per
run on purpose: a four-snapshot backstop run takes 45 minutes, and a per-run
ping would look like an outage while it was working correctly.

### Worker logs

The Worker emits one JSON line per invocation (`dispatch.start` and then
`dispatch.ok` or `dispatch.failed`/`dispatch.error`), persisted to Workers Logs
via the `[observability]` block in `wrangler.toml`. Read them in the dashboard
under the Worker's **Logs** tab, or live with:

```bash
cd cron && npx wrangler tail
```

Every line carries `scheduledTime` and `lagMs`, so if Cloudflare's cron ever
starts drifting the way GitHub's did, that shows up directly rather than having
to be inferred from run timestamps. Retention is 3 days on the free plan; the
healthchecks.io check, not these logs, is what alerts.

## Deploying

`.github/workflows/deploy-cron.yml` deploys on every push to `main` that
touches `cron/`. It needs two repository secrets:

- `CLOUDFLARE_API_TOKEN` — permissions: **Workers Scripts: Edit** and
  **Secrets Store: Edit** (Cloudflare requires *Edit*, not just *Read*, to bind
  a secret to a Worker during deployment).
- `CLOUDFLARE_ACCOUNT_ID`

To deploy by hand instead:

```bash
cd cron && npm install && npx wrangler deploy
```
