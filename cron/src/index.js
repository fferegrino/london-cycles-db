const DISPATCH_URL =
  "https://api.github.com/repos/fferegrino/london-cycles-db/actions/workflows/query.yml/dispatches";

// One JSON object per line so the dashboard can filter on the fields rather
// than on substrings of a sentence.
function log(level, fields) {
  console[level](JSON.stringify({ worker: "london-cycles-cron", ...fields }));
}

export default {
  // This Worker is driven entirely by its cron trigger. A fetch handler exists
  // only so that stray HTTP requests get a plain 404 instead of the runtime's
  // "Handler does not export a fetch() function" error. Dispatching from here
  // is deliberately not offered: an unauthenticated endpoint that fires a
  // workflow would be an open trigger for anyone who found the URL.
  async fetch() {
    return new Response("Cron-only Worker; nothing is served here.\n", {
      status: 404,
      headers: { "Content-Type": "text/plain" },
    });
  },

  async scheduled(event, env) {
    const started = Date.now();
    const base = {
      cron: event.cron,
      scheduledTime: new Date(event.scheduledTime).toISOString(),
      // The gap between when the trigger was due and when it actually ran.
      // Delivery lag is what made GitHub's scheduler unusable, so it is worth
      // watching here too rather than assuming Cloudflare is punctual.
      lagMs: started - event.scheduledTime,
    };

    log("log", { event: "dispatch.start", ...base });

    let response;
    try {
      const token = await env.GH_PAT.get();

      response = await fetch(DISPATCH_URL, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          Accept: "application/vnd.github+json",
          "X-GitHub-Api-Version": "2022-11-28",
          "User-Agent": "london-cycles-cron",
        },
        body: JSON.stringify({ ref: "main", inputs: { snapshots: "1" } }),
      });
    } catch (error) {
      log("error", {
        event: "dispatch.error",
        ...base,
        durationMs: Date.now() - started,
        error: String(error),
      });
      throw error;
    }

    // A dispatch that silently fails looks exactly like GitHub's own dropped
    // schedule events, so record the response and rethrow: the throw marks the
    // invocation as errored, which is what the dashboard filters on.
    if (!response.ok) {
      const body = await response.text();
      log("error", {
        event: "dispatch.failed",
        ...base,
        durationMs: Date.now() - started,
        status: response.status,
        // GitHub's error bodies are short, but a runaway one would eat into the
        // 256 KB per-log limit.
        body: body.slice(0, 1000),
        rateLimitRemaining: response.headers.get("x-ratelimit-remaining"),
      });
      throw new Error(`workflow_dispatch failed: ${response.status} ${body}`);
    }

    log("log", {
      event: "dispatch.ok",
      ...base,
      durationMs: Date.now() - started,
      status: response.status,
      rateLimitRemaining: response.headers.get("x-ratelimit-remaining"),
    });
  },
};
