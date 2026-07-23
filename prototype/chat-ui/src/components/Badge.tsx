// Small reusable rounded-capsule pill / badge. Purely presentational — colors
// come from the shared design tokens so both light and dark themes work.
import type { ReactNode } from "react";
import type { Translate } from "@/lib/lang";

// Visual tones. Semantic ones (done/pending/failed) map to --ok / --warn /
// --danger; the rest are neutral tints reused across views.
export type BadgeTone =
  | "tool"
  | "kind"
  | "topic"
  | "neutral"
  | "done"
  | "pending"
  | "failed";

export function Badge({
  tone = "neutral",
  children,
  className,
  title,
}: {
  tone?: BadgeTone;
  children: ReactNode;
  className?: string;
  title?: string;
}) {
  return (
    <span
      className={`loom-badge loom-badge--${tone}${className ? " " + className : ""}`}
      title={title}
    >
      {children}
    </span>
  );
}

// Map a free-form status/state string onto a semantic tone.
// Returns null when there is nothing status-like to show.
export function statusTone(state?: string | null): BadgeTone | null {
  if (!state) return null;
  const s = String(state).toLowerCase();
  if (/(done|complete|completed|success|succeeded|ok|finished|resolved|closed)/.test(s))
    return "done";
  if (/(pending|progress|running|waiting|queued|todo|open|active|in[-_ ]?progress)/.test(s))
    return "pending";
  if (/(overdue|fail|failed|error|expired|stale|blocked|cancell?ed)/.test(s))
    return "failed";
  return "neutral";
}

// Map a raw tool name onto a slug class so each source gets its own muted,
// theme-aware color (defined in polish.css as .loom-badge--tool.tool-*).
// Shared by the ledger table and the record cards (Home / Topics / Calendar).
const TOOL_SLUG: Record<string, string> = {
  git: "git",
  claude: "claude",
  codex: "codex",
  cursor: "cursor",
  codebuddy: "codebuddy",
  feishu: "feishu",
  docs: "docs",
  notes: "notes",
  日报: "report",
};
export function toolSlug(tool?: string | null): string {
  return `tool-${TOOL_SLUG[String(tool || "").trim().toLowerCase()] || "default"}`;
}

// Localize a status string for display. Known Chinese/English statuses map to a
// bilingual label (已完成/待处理/逾期 ↔ done/pending/overdue); anything else is
// shown as-is so data-driven states still render.
export function statusLabel(t: Translate, state?: string | null): string {
  if (!state) return "";
  const tone = statusTone(state);
  if (tone === "done") return t("已完成", "Done");
  if (tone === "pending") return t("待处理", "Pending");
  if (tone === "failed") return t("逾期", "Overdue");
  return state;
}
