# london-cycles-cron

A Cloudflare Worker whose only job is to fire `workflow_dispatch` on
`.github/workflows/query.yml` every fifteen minutes.

GitHub's own `schedule` trigger is best-effort: it delivers events late and
drops them when they are late enough that the next occurrence has come round.
In practice this repo saw roughly one in nine hourly triggers honoured. This
Worker takes over as the normal path; the `schedule` entry in `query.yml`
remains as a backstop.

## Setup

The GitHub PAT (scope: `repo`, or `actions: write` on a fine-grained token)
lives in the account Secrets Store as `GH_PAT_LONDON_CYCLES_DB` and is bound to
the Worker as `GH_PAT`. Fill `store_id` in `wrangler.toml` with the id from:

```bash
wrangler secrets-store store list --remote
```

## Deploying

`.github/workflows/deploy-cron.yml` deploys on every push to `main` that
touches `cron/`. It needs two repository secrets:

- `CLOUDFLARE_API_TOKEN` — permissions: Workers Scripts:Edit, and
  Secrets Store:Read so the binding can be attached at deploy time.
- `CLOUDFLARE_ACCOUNT_ID`

To deploy by hand instead:

```bash
cd cron && npm install && npx wrangler deploy
```
