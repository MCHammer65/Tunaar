// File an Autopilot issue from Node (>=18, global fetch). Best-effort.
export async function fileIssue(title, body, labels = ["feature", "needs-triage"]) {
  const repo = process.env.AUTOPILOT_REPO || "OWNER/REPO";
  const token = process.env.AUTOPILOT_GITHUB_TOKEN;
  if (!token) return false;
  try {
    const r = await fetch(`https://api.github.com/repos/${repo}/issues`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}`, Accept: "application/vnd.github+json" },
      body: JSON.stringify({ title, body, labels }),
    });
    return r.status === 201;
  } catch { return false; }
}

// Self-healing: call from a global error handler (opt-in, vendor-side).
export async function reportError(err) {
  if (process.env.AUTOPILOT_REPORT_ERRORS !== "true") return false;
  return fileIssue(`[auto] ${err.name}: ${String(err.message).slice(0, 80)}`,
    "```\n" + (err.stack || "").slice(0, 4000) + "\n```",
    ["bug", "auto-fix", "needs-triage"]);
}
