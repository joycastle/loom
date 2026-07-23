import { useEffect, useRef, useState } from "react";
import { X, FileText, Hash } from "lucide-react";
import { useLoom } from "@/runtime/LoomProvider";
import { Badge, toolSlug } from "@/components/Badge";
import { useT, type Translate } from "@/lib/lang";
import type { LoomCard, LoomEntryDetail, LoomSearchHit } from "@/types/loom";

// Bilingual labels for record kinds (falls back to the raw value).
const KIND_LABELS: Record<string, [string, string]> = {
  session: ["对话", "Session"],
  commit: ["提交", "Commit"],
  note: ["笔记", "Note"],
  doc: ["文档", "Doc"],
  data: ["数据", "Data"],
  report: ["日报", "Report"],
  requirement: ["需求", "Requirement"],
  clip: ["剪藏", "Clip"],
  other: ["其他", "Other"],
};

export function kindLabel(t: Translate, kind?: string): string {
  if (!kind) return t("记录", "Record");
  const pair = KIND_LABELS[kind];
  return pair ? t(pair[0], pair[1]) : kind;
}

// Bilingual labels for the detail prose fields.
const PROSE_LABELS_I18N: Record<string, [string, string]> = {
  digest: ["摘要", "Summary"],
  body: ["正文", "Body"],
  opening: ["开场", "Opening"],
  content: ["内容", "Content"],
  work: ["工作", "Work"],
  thinking: ["思考", "Thinking"],
  plan: ["计划", "Plan"],
};

// Detail fields we render as their own prose block, in priority order.
const PROSE_FIELDS = [
  "digest",
  "body",
  "opening",
  "content",
  "work",
  "thinking",
  "plan",
] as const;

// Escape a search snippet, then re-allow only <mark> highlight tags. This keeps
// backend highlight markup working without opening an XSS hole.
export function snipHtml(snip: string): string {
  const esc = snip
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
  return esc.replace(/&lt;mark&gt;/g, "<mark>").replace(/&lt;\/mark&gt;/g, "</mark>");
}

/** A single record card — a button that opens the detail drawer. */
export function RecordCard({ card }: { card: LoomCard | LoomSearchHit }) {
  const { openRecord } = useLoom();
  const t = useT();
  const snip = (card as LoomSearchHit).snip;
  return (
    <button
      type="button"
      className="loom-rec-card"
      onClick={() => openRecord(card.id)}
      title={t("查看记录详情", "View record details")}
    >
      <div className="loom-rec-meta">
        {card.tool ? <Badge tone="tool" className={toolSlug(card.tool)}>{card.tool}</Badge> : null}
        <span className="loom-rec-kind">{kindLabel(t, card.kind)}</span>
        {card.date ? <span className="loom-rec-date">{card.date}</span> : null}
        {card.project ? <span className="loom-rec-proj">{card.project}</span> : null}
      </div>
      {snip ? (
        <div
          className="loom-rec-summary"
          dangerouslySetInnerHTML={{ __html: snipHtml(snip) }}
        />
      ) : (
        <div className="loom-rec-summary">{card.summary || t("(无摘要)", "(no summary)")}</div>
      )}
      {card.topics?.length ? (
        <div className="loom-rec-topics">
          {card.topics.map((t) => (
            <span key={t} className="loom-rec-topic">
              <Hash size={10} strokeWidth={2.4} />
              {t}
            </span>
          ))}
        </div>
      ) : null}
    </button>
  );
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

function DetailBody({ entry }: { entry: LoomEntryDetail }) {
  const t = useT();
  const detail = isPlainObject(entry.detail) ? entry.detail : {};
  const rendered = new Set<string>();
  const proseBlocks: { key: string; label: string; text: string }[] = [];
  for (const field of PROSE_FIELDS) {
    const value = detail[field];
    if (typeof value === "string" && value.trim()) {
      const pair = PROSE_LABELS_I18N[field];
      proseBlocks.push({ key: field, label: pair ? t(pair[0], pair[1]) : field, text: value });
      rendered.add(field);
    }
  }

  // Anything else in `detail` gets dumped as readable JSON.
  const rest: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(detail)) {
    if (rendered.has(key)) continue;
    if (value === null || value === undefined || value === "") continue;
    rest[key] = value;
  }

  return (
    <>
      {proseBlocks.map((block) => (
        <section key={block.key} className="loom-drawer-section">
          <h4>{block.label}</h4>
          <p className="loom-drawer-prose">{block.text}</p>
        </section>
      ))}
      {Object.keys(rest).length ? (
        <section className="loom-drawer-section">
          <h4>{t("其他字段", "Other fields")}</h4>
          <pre className="loom-drawer-json">{JSON.stringify(rest, null, 2)}</pre>
        </section>
      ) : null}
    </>
  );
}

/** Right-side slide-in showing one record's full detail. */
export function RecordDrawer() {
  const t = useT();
  const { openRecordId, closeRecord, ledger } = useLoom();
  const [entry, setEntry] = useState<LoomEntryDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const panelRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!openRecordId) return;
    let cancelled = false;
    setEntry(null);
    setError(null);
    setLoading(true);
    void (async () => {
      try {
        const data = await ledger.entry(openRecordId);
        if (cancelled) return;
        if (data.error) setError(data.error);
        else setEntry(data);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [openRecordId, ledger]);

  // Close on Escape.
  useEffect(() => {
    if (!openRecordId) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeRecord();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [openRecordId, closeRecord]);

  if (!openRecordId) return null;

  return (
    <div className="loom-drawer-scrim" onClick={closeRecord}>
      <div
        className="loom-drawer"
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="loom-drawer-head">
          <span className="loom-drawer-title">
            <FileText size={14} strokeWidth={2} />
            {t("记录详情", "Record details")}
          </span>
          <button
            type="button"
            className="loom-icon-btn"
            onClick={closeRecord}
            title={t("关闭", "Close")}
          >
            <X size={16} strokeWidth={2} />
          </button>
        </div>
        <div className="loom-drawer-body">
          {loading ? <p className="loom-drawer-hint">{t("加载中…", "Loading…")}</p> : null}
          {error ? <p className="loom-drawer-hint">{t("无法打开:", "Cannot open: ")}{error}</p> : null}
          {entry ? (
            <>
              <div className="loom-drawer-meta">
                {entry.tool ? <Badge tone="tool" className={toolSlug(entry.tool)}>{entry.tool}</Badge> : null}
                <span className="loom-rec-kind">{kindLabel(t, entry.kind)}</span>
                {entry.date ? <span className="loom-rec-date">{entry.date}</span> : null}
                {entry.project ? (
                  <span className="loom-rec-proj">{entry.project}</span>
                ) : null}
              </div>
              {entry.summary ? (
                <p className="loom-drawer-summary">{entry.summary}</p>
              ) : null}
              {entry.topics?.length ? (
                <div className="loom-rec-topics">
                  {entry.topics.map((t) => (
                    <span key={t} className="loom-rec-topic">
                      <Hash size={10} strokeWidth={2.4} />
                      {t}
                    </span>
                  ))}
                </div>
              ) : null}
              {entry.ref ? (
                <section className="loom-drawer-section">
                  <h4>{t("来源", "Source")}</h4>
                  <code className="loom-drawer-ref">{entry.ref}</code>
                </section>
              ) : null}
              <DetailBody entry={entry} />
            </>
          ) : null}
        </div>
      </div>
    </div>
  );
}
