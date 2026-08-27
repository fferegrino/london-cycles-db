const DISPATCH_URL =
  "https://api.github.com/repos/fferegrino/london-cycles-db/actions/workflows/query.yml/dispatches";

export default {
  async scheduled(event, env) {
    const token = await env.GH_PAT.get();

    const response = await fetch(DISPATCH_URL, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "london-cycles-cron",
      },
      body: JSON.stringify({ ref: "main", inputs: { snapshots: "1" } }),
    });

    // A dispatch that silently fails looks exactly like GitHub's own dropped
    // schedule events, so throw and let it show up in the Worker's logs.
    if (!response.ok) {
      throw new Error(
        `workflow_dispatch failed: ${response.status} ${await response.text()}`,
      );
    }
  },
};
