// Faithful React port of browse.html's Ledger view (#v-ledger):
// full-text search + tool/date filters + paginated result cards + record drawer.
// DOM + class names mirror browse.html so browse.css styles it identically.
import { useCallback, useEffect, useRef, useState } from "react";
import { useLoom } from "@/runtime/LoomProvider";
import { kindLabel, snipHtml } from "@/components/RecordDrawer";
import { Badge, statusTone, statusLabel, toolSlug } from "@/components/Badge";
import { DatePicker } from "@/components/DatePicker";
import { useT, useLang } from "@/lib/lang";
import type { LoomSearchHit } from "@/types/loom";

// Emoji glyph per record kind — matches browse.html's KIND map.
const KIND: Record<string, string> = {
  session: "💬",
  commit: "💻",
  doc: "📄",
  note: "📎",
  report: "📋",
  requirement: "📥",
};

// Tool filter options — same fixed list browse.html appends to #f-tool.
const TOOLS = [
  "git",
  "claude",
  "codex",
  "cursor",
  "codebuddy",
  "feishu",
  "docs",
  "notes",
  "日报",
];

const DEBOUNCE_MS = 280;

// One table row — clicking (or Enter/Space) opens the detail drawer via
// openRecord(id). Tool + kind render as colored pills; date is right-aligned
// with tabular figures; the summary is the emphasized wide column and carries
// the search snippet underneath when present.
function LedgerRow({
  hit,
  onOpen,
}: {
  hit: LoomSearchHit;
  onOpen: (id: string) => void;
}) {
  const t = useT();
  const open = () => onOpen(hit.id);
  // Some records (e.g. console/agent items) may carry a status/state field.
  const state = (hit as { state?: string; status?: string }).state ??
    (hit as { state?: string; status?: string }).status;
  const tone = statusTone(state);
  return (
    <tr
      role="button"
      tabIndex={0}
      onClick={open}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          open();
        }
      }}
    >
      <td className="lt-date">{hit.date}</td>
      <td className="lt-proj">{hit.project || "—"}</td>
      <td>
        {hit.tool ? (
          <Badge tone="tool" className={toolSlug(hit.tool)}>
            {hit.tool}
          </Badge>
        ) : null}
      </td>
      <td>
        <span className="lt-pills">
          <Badge tone="kind">
            {KIND[hit.kind ?? ""] || ""} {kindLabel(t, hit.kind)}
          </Badge>
          {tone ? <Badge tone={tone}>{statusLabel(t, state)}</Badge> : null}
        </span>
      </td>
      <td className="lt-summary">
        <div className="lt-summary-main">{hit.summary || t("(无摘要)", "(no summary)")}</div>
        {hit.snip ? (
          // snip may carry <mark> highlight tags; snipHtml escapes everything
          // else so this is safe to inline.
          <div
            className="lt-snip"
            dangerouslySetInnerHTML={{ __html: snipHtml(hit.snip) }}
          />
        ) : null}
      </td>
      <td>
        {hit.topics && hit.topics.length ? (
          <span className="lt-topics">
            {hit.topics.map((t) => (
              <Badge key={t} tone="topic">
                {t}
              </Badge>
            ))}
          </span>
        ) : null}
      </td>
    </tr>
  );
}

// Compact page list with gaps — mirrors browse.html's ledgerPageItems().
function pageItems(page: number, pages: number): Array<number | "gap"> {
  const keep = new Set<number>([1, pages]);
  for (let p = page - 2; p <= page + 2; p++) {
    if (p >= 1 && p <= pages) keep.add(p);
  }
  const nums = [...keep].sort((a, b) => a - b);
  const items: Array<number | "gap"> = [];
  let prev = 0;
  for (const p of nums) {
    if (prev && p - prev > 1) items.push("gap");
    items.push(p);
    prev = p;
  }
  return items;
}

export function LedgerView() {
  const t = useT();
  const { lang } = useLang();
  const { ledger, openRecord } = useLoom();

  // Filter state. `q` is the live input value; `query` is its debounced,
  // committed form that actually drives searches.
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const [tool, setTool] = useState("");
  // Default the ledger to the last 7 days (local time). Users can clear/widen it.
  const [since, setSince] = useState(() => {
    const d = new Date();
    d.setDate(d.getDate() - 7);
    d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
    return d.toISOString().slice(0, 10);
  });
  const [until, setUntil] = useState("");
  const [pageSize, setPageSize] = useState(20);
  const [page, setPage] = useState(1);

  // Result state.
  const [hits, setHits] = useState<LoomSearchHit[]>([]);
  const [total, setTotal] = useState(0);
  const [pages, setPages] = useState(1);
  const [busy, setBusy] = useState(false);
  const [resultTitle, setResultTitle] = useState(() => t("最近记录", "Recent records"));
  const [countText, setCountText] = useState("");
  // When set, #r-search shows an `.empty` notice instead of cards.
  const [notice, setNotice] = useState<string | null>(null);
  // Grand total across the whole ledger (unfiltered) for the stats strip —
  // fetched once from the existing /api/stats client method.
  const [grandTotal, setGrandTotal] = useState<number | null>(null);

  const seqRef = useRef(0);
  const titleRef = useRef<HTMLHeadingElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  // Debounce the query: settle input into `query` and reset to page 1.
  useEffect(() => {
    const id = setTimeout(() => {
      setQuery(q.trim());
      setPage(1);
    }, DEBOUNCE_MS);
    return () => clearTimeout(id);
  }, [q]);

  // The one search effect — reruns whenever committed filters or page change.
  useEffect(() => {
    const seq = ++seqRef.current;
    const filtered = !!(query || tool || since || until);
    setResultTitle(
      query
        ? t("搜索结果", "Search results")
        : filtered
          ? t("筛选结果", "Filtered results")
          : t("最近记录", "Recent records"),
    );
    setCountText(t("正在搜索…", "Searching…"));
    setBusy(true);

    if (since && until && since > until) {
      setCountText(t("日期范围有误", "Invalid date range"));
      setNotice(t("起始日期不能晚于截止日期", "Start date cannot be after end date"));
      setHits([]);
      setTotal(0);
      setPages(1);
      setBusy(false);
      return;
    }

    void (async () => {
      try {
        const r = await ledger.search({
          q: query || undefined,
          tool: tool || undefined,
          since: since || undefined,
          until: until || undefined,
          // The sidecar backend paginates by page/page_size and ignores offset;
          // the mock client paginates by limit/offset. Send both so the clicked
          // page actually fetches its rows regardless of backend.
          limit: pageSize,
          offset: (page - 1) * pageSize,
          page,
          page_size: pageSize,
        });
        if (seq !== seqRef.current) return;
        const totalPages = Math.max(1, r.pages || 1);
        const curPage = Math.min(totalPages, Math.max(1, r.page || page));
        setTotal(r.total);
        setPages(totalPages);
        setHits(r.hits);
        setCountText(
          r.total
            ? t(`共 ${r.total} 条 · 第 ${curPage}/${totalPages} 页`, `${r.total} total · page ${curPage}/${totalPages}`)
            : t("0 条", "0 results"),
        );
        setNotice(
          r.hits.length ? null : filtered ? t("无符合条件的记录", "No matching records") : t("暂无记录", "No records yet"),
        );
      } catch {
        if (seq !== seqRef.current) return;
        setCountText(t("加载失败", "Failed to load"));
        setNotice(t("记录暂时无法载入,请稍后重试", "Records could not load. Please try again later."));
        setHits([]);
      } finally {
        if (seq === seqRef.current) setBusy(false);
      }
    })();
  }, [query, tool, since, until, pageSize, page, ledger, t]);

  // Grand total (unfiltered) for the stats strip — fetched once on mount.
  useEffect(() => {
    let alive = true;
    void (async () => {
      try {
        const s = await ledger.stats();
        if (alive) setGrandTotal(s.entries);
      } catch {
        // Non-fatal: the strip simply omits the grand-total item.
      }
    })();
    return () => {
      alive = false;
    };
  }, [ledger]);

  // ⌘K / Ctrl+K focuses the search box while the Ledger view is visible.
  // (Cross-view activation lives in the shell router, which this file can't
  // touch; when the view is hidden the input has no offsetParent so we skip.)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        const el = inputRef.current;
        if (el && el.offsetParent !== null) {
          e.preventDefault();
          el.focus();
        }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  const goPage = useCallback((next: number) => {
    setPage(Math.max(1, next));
    titleRef.current?.scrollIntoView({ block: "start" });
  }, []);

  const onQueryKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Escape") {
      setQ("");
      setQuery("");
      setPage(1);
    }
  };

  const showPager = total > 0 && pages > 1;
  const items = pageItems(page, pages);

  // ---- summary-stats strip (live, bound to the current filtered `total`) ----
  // Only non-query filters count toward the "筛选出" wording; a query switches
  // to "搜索到"; nothing active falls back to "共".
  const filtered = !!(tool || since || until);
  const num = <b className="ls-num">{total.toLocaleString()}</b>;
  const liveCount =
    lang === "en" ? (
      <>
        {num} {query ? "results" : filtered ? "filtered" : "total"}
      </>
    ) : (
      <>
        {query ? "搜索到 " : filtered ? "筛选出 " : "共 "}
        {num} 条
      </>
    );
  // Current 1-based page range (clamp the page like the search effect does).
  const curPage = Math.min(pages, Math.max(1, page));
  const rangeFrom = total ? (curPage - 1) * pageSize + 1 : 0;
  const rangeTo = Math.min(total, curPage * pageSize);

  return (
    <>
      <div className="ledger-head">
        <h1>{t("台账", "Ledger")}</h1>
        <p>{t("搜索、筛选并查看所有工作记录。", "Search, filter, and review all work records.")}</p>
      </div>
      <div className="ledger-tools">
        <div className="ledger-stats" aria-live="polite">
          <span className="ledger-stat ledger-stat--live">{liveCount}</span>
          {total > 0 ? (
            <span className="ledger-stat ledger-stat--muted">
              {lang === "en" ? (
                <>
                  {rangeFrom.toLocaleString()}–{rangeTo.toLocaleString()} shown
                </>
              ) : (
                <>
                  第 {rangeFrom.toLocaleString()}–{rangeTo.toLocaleString()} 条
                </>
              )}
            </span>
          ) : null}
          {grandTotal !== null ? (
            <span className="ledger-stat ledger-stat--muted">
              {t(
                `台账共 ${grandTotal.toLocaleString()} 条`,
                `${grandTotal.toLocaleString()} in ledger`,
              )}
            </span>
          ) : null}
        </div>
        <div className="spot">
          <label className="sr-only" htmlFor="q">
            {t("搜索台账", "Search ledger")}
          </label>
          <input
            type="search"
            id="q"
            name="ledger_query"
            autoComplete="off"
            spellCheck={false}
            ref={inputRef}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={onQueryKeyDown}
          />
          <span className="kbd">⌘K</span>
        </div>

        <div className="bar">
          <label className="sr-only" htmlFor="f-tool">
            {t("工具过滤", "Tool filter")}
          </label>
          <select
            id="f-tool"
            name="tool_filter"
            value={tool}
            onChange={(e) => {
              setTool(e.target.value);
              setPage(1);
            }}
          >
            <option value="">{t("全部工具", "All Tools")}</option>
            {TOOLS.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
          <DatePicker
            value={since}
            onChange={(v) => {
              setSince(v);
              setPage(1);
            }}
            placeholder={t("起始日期", "Start date")}
            ariaLabel={t("起始日期", "Start date")}
          />
          <DatePicker
            value={until}
            onChange={(v) => {
              setUntil(v);
              setPage(1);
            }}
            placeholder={t("截止日期", "End date")}
            ariaLabel={t("截止日期", "End date")}
          />
        </div>

        <div className="ledger-result-head">
          <h2 id="ledger-result-title" ref={titleRef}>
            {resultTitle}
          </h2>
          <div className="ledger-result-meta">
            <span id="ledger-result-count" aria-live="polite">
              {countText}
            </span>
            <label className="ledger-page-size" htmlFor="f-page-size">
              <span>{t("每页", "Per page")}</span>
              <select
                id="f-page-size"
                name="page_size"
                value={pageSize}
                onChange={(e) => {
                  setPageSize(Number(e.target.value) || 20);
                  setPage(1);
                }}
              >
                <option value="10">10</option>
                <option value="20">20</option>
                <option value="50">50</option>
                <option value="100">100</option>
              </select>
            </label>
          </div>
        </div>

        <div id="r-search" aria-busy={busy}>
          {notice !== null && hits.length === 0 ? (
            <div className="empty">{notice}</div>
          ) : (
            <div className="ledger-table-wrap">
              <table className="ledger-table">
                <thead>
                  <tr>
                    <th className="lt-date">{t("日期", "Date")}</th>
                    <th>{t("项目", "Project")}</th>
                    <th>{t("工具", "Tool")}</th>
                    <th>{t("类型", "Kind")}</th>
                    <th className="lt-summary">{t("摘要", "Summary")}</th>
                    <th>{t("主题", "Topics")}</th>
                  </tr>
                </thead>
                <tbody>
                  {hits.map((hit) => (
                    <LedgerRow key={hit.id} hit={hit} onOpen={openRecord} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div
          className="ledger-pagination"
          id="ledger-pagination"
          role="navigation"
          aria-label={t("台账分页", "Ledger pagination")}
          aria-busy={busy}
          hidden={!showPager}
        >
          {showPager ? (
            <>
              <button
                type="button"
                className="ledger-page-btn"
                onClick={() => goPage(page - 1)}
                disabled={page <= 1}
              >
                {t("上一页", "Previous")}
              </button>
              {items.map((item, i) =>
                item === "gap" ? (
                  <span
                    key={`gap-${i}`}
                    className="ledger-page-gap"
                    aria-hidden="true"
                  >
                    …
                  </span>
                ) : (
                  <button
                    key={item}
                    type="button"
                    className={`ledger-page-btn${item === page ? " on" : ""}`}
                    onClick={() => goPage(item)}
                    aria-current={item === page ? "page" : undefined}
                    aria-label={t(`第 ${item} 页`, `Page ${item}`)}
                  >
                    {item}
                  </button>
                ),
              )}
              <button
                type="button"
                className="ledger-page-btn"
                onClick={() => goPage(page + 1)}
                disabled={page >= pages}
              >
                {t("下一页", "Next")}
              </button>
            </>
          ) : null}
        </div>
      </div>
    </>
  );
}
