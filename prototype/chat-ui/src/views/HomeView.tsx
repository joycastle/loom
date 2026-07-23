// Home / work-overview view for the loom serve admin console.
//
// Reproduces browse.html's home DOM + class names so the shared browse.css
// styles it identically: greeting, sync-status row, "today" metrics, a link to
// the report workspace, the recent-records list, and the workspace-status
// panel. Chat/assistant handoff and enterprise (Feishu/company-AI) status have
// been removed — this is a local admin surface.

import { useCallback, useEffect, useState } from "react";
import { RefreshCw, Check, X } from "lucide-react";
import { useLoom } from "@/runtime/LoomProvider";
import { useAppRouter } from "@/lib/app-router";
import { RecordCard } from "@/components/RecordDrawer";
import { localISODate } from "@/lib/id";
import { useLang, useT, type Lang, type Translate } from "@/lib/lang";
import type { LoomHome } from "@/types/loom";

// Shape of the sync result nested inside the admin-action response.
type SyncSource = { status: string; count?: number };
type SyncResult = {
  status?: string;
  sources?: SyncSource[];
  backup?: { ok?: boolean };
};
type SyncPhase = "running" | "success" | "partial" | "error";

function formatHomeDate(day: string, lang: Lang): string {
  const d = new Date(day + "T12:00:00");
  return new Intl.DateTimeFormat(lang === "zh" ? "zh-CN" : "en-US", {
    month: "long",
    day: "numeric",
    weekday: "long",
  }).format(d);
}

function homeSyncDetail(sync: SyncResult, t: Translate, message?: string): string {
  const rows = sync.sources || [];
  const counts: Record<string, number> = { success: 0, partial: 0, error: 0 };
  rows.forEach((r) => {
    counts[r.status] = (counts[r.status] || 0) + 1;
  });
  const records = rows.reduce((n, r) => n + (Number(r.count) || 0), 0);
  const parts: string[] = [];
  if (counts.success) parts.push(t(`${counts.success} 个来源成功`, `${counts.success} sources succeeded`));
  if (counts.partial) parts.push(t(`${counts.partial} 个来源部分完成`, `${counts.partial} sources partial`));
  if (counts.error) parts.push(t(`${counts.error} 个来源失败`, `${counts.error} sources failed`));
  if (records) parts.push(t(`${records} 条新记录`, `${records} new records`));
  if (sync.backup) parts.push(sync.backup.ok ? t("备份完成", "backup completed") : t("备份失败", "backup failed"));
  return parts.join(" · ") || message || t("没有可执行的数据来源", "No source available to run");
}

function HomeMetric({ value, label }: { value: number; label: string }) {
  return (
    <div className="home-metric">
      <b>{Number(value) || 0}</b>
      <span>{label}</span>
    </div>
  );
}

function HomeStatusRow({ label, value, state = "" }: { label: string; value: string; state?: string }) {
  return (
    <div className="home-status-row">
      <span className="home-status-label">
        <i className={`status-dot ${state}`.trim()} />
        <span>{label}</span>
      </span>
      <b>{value}</b>
    </div>
  );
}

export function HomeView() {
  const t = useT();
  const { lang } = useLang();
  const { ledger } = useLoom();
  const { view, setView } = useAppRouter();
  const client = ledger;

  const [home, setHome] = useState<LoomHome | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  const [syncPhase, setSyncPhase] = useState<SyncPhase | null>(null);
  const [syncTitle, setSyncTitle] = useState("");
  const [syncDetail, setSyncDetail] = useState("");
  const [syncing, setSyncing] = useState(false);

  const loadDash = useCallback(async () => {
    setLoading(true);
    setError(false);
    try {
      let data: LoomHome;
      if (typeof client.home === "function") {
        data = await client.home();
      } else {
        const stats = await ledger.stats();
        data = {
          today: localISODate(),
          today_entries: 0,
          total_entries: stats.entries,
          summarized: 0,
          classified: stats.tagged,
          source_counts: stats.tools,
          active_sources: Object.keys(stats.tools).length,
          available_sources: Object.keys(stats.tools).length,
          recent: stats.recent.slice(0, 6),
        };
      }
      setHome(data);
    } catch {
      setError(true);
      setHome(null);
    } finally {
      setLoading(false);
    }
  }, [client, ledger]);

  // Refetch whenever Home becomes the active view (all views stay mounted).
  useEffect(() => {
    if (view === "home") void loadDash();
  }, [view, loadDash]);

  const homeSync = async () => {
    if (syncing) return;
    setSyncing(true);
    setSyncPhase("running");
    setSyncTitle(t("正在同步最新记录", "Syncing latest records"));
    setSyncDetail(t("正在更新已开启的数据来源,并在本地生成备份…", "Updating enabled sources and creating a local backup…"));
    try {
      const r = await client.adminAction({ action: "sync", source: "all", since: "", backup: true, push: false });
      const sync: SyncResult =
        (r as { sync?: SyncResult }).sync || ({ status: r.ok ? "success" : "error", sources: [] } as SyncResult);
      const status: SyncPhase = (["success", "partial", "error"] as string[]).includes(String(sync.status))
        ? (sync.status as SyncPhase)
        : "error";
      setSyncPhase(status);
      setSyncTitle(
        status === "success"
          ? t("同步完成", "Sync completed")
          : status === "partial"
            ? t("同步部分完成", "Sync partially completed")
            : t("同步失败", "Sync failed"),
      );
      const detail = homeSyncDetail(sync, t, r.message);
      setSyncDetail(detail);
      if (status !== "error") {
        try {
          await loadDash();
        } catch {
          setSyncDetail(`${detail} · ${t("首页数据暂未刷新", "Home data did not refresh")}`);
        }
      }
    } catch (e) {
      setSyncPhase("error");
      setSyncTitle(t("同步失败", "Sync failed"));
      setSyncDetail(e instanceof Error ? e.message : String(e));
    } finally {
      setSyncing(false);
    }
  };

  const n = Number(home?.today_entries) || 0;
  const sourceEntries = Object.entries(home?.source_counts || {});
  const dateLabel = home ? `${t("今天", "Today")} · ${formatHomeDate(home.today, lang)}` : t("今天", "Today");
  const summary = error
    ? t("本地记录暂时无法载入,请重试。", "Local records could not load. Please retry.")
    : home
      ? n
        ? t(
            `本地已整理 ${n} 条工作记录,来自 ${sourceEntries.length} 个来源。`,
            `${n} work records organized locally from ${sourceEntries.length} sources.`,
          )
        : t("今天还没有新记录;同步后,这里会显示真实工作进展。", "No new records today. After a sync, real progress shows here.")
      : t("正在读取今天的工作记录…", "Loading today's work…");
  const recentCaption = n
    ? t(`今天最近 ${Math.min(6, home?.recent?.length || 0)} 条`, `${Math.min(6, home?.recent?.length || 0)} most recent today`)
    : t("今天为空,显示整个台账的最近记录", "Today is empty; showing the latest across the ledger");

  return (
    <div className="home-shell">
      <div className="home-page-head">
        <div className="home-heading">
          <div className="home-kicker" id="home-date-label">
            {dateLabel}
          </div>
          <h1>{t("工作概览", "Work overview")}</h1>
          <p id="home-summary">{summary}</p>
        </div>
        <div className="home-actions">
          <button className="act" id="home-sync-btn" onClick={() => void homeSync()} disabled={syncing}>
            <span id="home-sync-icon">
              <RefreshCw size={16} strokeWidth={2} />
            </span>
            <span>{t("同步记录", "Sync records")}</span>
          </button>
        </div>
      </div>

      {syncPhase ? (
        <div id="home-sync-state" className={`home-sync-state ${syncPhase}`} aria-live="polite">
          <span className="home-sync-mark" id="home-sync-mark">
            {syncPhase === "running" ? (
              <span className="admin-spinner" aria-hidden="true" />
            ) : syncPhase === "success" ? (
              <Check size={16} strokeWidth={2} />
            ) : syncPhase === "partial" ? (
              <RefreshCw size={16} strokeWidth={2} />
            ) : (
              <X size={16} strokeWidth={2} />
            )}
          </span>
          <div className="home-sync-copy">
            <strong id="home-sync-title">{syncTitle}</strong>
            <span id="home-sync-detail">{syncDetail}</span>
          </div>
        </div>
      ) : null}

      <div className="home-dashboard">
        {/* ---- today's work ---- */}
        <section className="home-panel home-today">
          <div className="home-panel-head">
            <div className="home-panel-title">
              <h2>{t("今日工作", "Today's work")}</h2>
              <p>{t("只展示已经进入本地台账的真实记录", "Only work already captured in your local ledger")}</p>
            </div>
            <button className="home-panel-link" onClick={() => setView("calendar", true)}>
              {t("查看今天", "Open today")}
            </button>
          </div>
          <div className="home-metrics" id="home-today-metrics">
            {error ? (
              <div className="home-error" style={{ gridColumn: "1/-1" }}>
                <span>{t("首页数据加载失败,但台账和设置仍可单独打开。", "Home data failed to load, but the ledger and settings still open.")}</span>
                <button className="act" onClick={() => void loadDash()}>
                  {t("重试", "Retry")}
                </button>
              </div>
            ) : loading || !home ? (
              <>
                <div className="home-metric home-skeleton">0</div>
                <div className="home-metric home-skeleton">0</div>
                <div className="home-metric home-skeleton">0</div>
              </>
            ) : (
              <>
                <HomeMetric value={n} label={t("已采集", "Collected")} />
                <HomeMetric value={home.summarized} label={t("已摘要", "Summarized")} />
                <HomeMetric value={home.classified} label={t("已归类", "Classified")} />
              </>
            )}
          </div>
          <div className="home-source-row" id="home-source-row">
            {error ? null : loading || !home ? (
              <span className="home-muted">{t("正在统计来源…", "Loading sources…")}</span>
            ) : sourceEntries.length ? (
              sourceEntries.map(([name, count]) => (
                <span className="home-source-chip" key={name}>
                  <span>{name}</span>
                  <b>{Number(count) || 0}</b>
                </span>
              ))
            ) : (
              <span className="home-muted">{t("同步记录后会按来源展示今天的工作。", "After syncing, today's work is shown by source.")}</span>
            )}
          </div>
        </section>

        {/* ---- daily report workspace link ---- */}
        <section className="home-panel home-report">
          <div className="home-panel-head">
            <div className="home-panel-title">
              <h2>{t("日报", "Daily report")}</h2>
              <p>{t("查看历史日报,或导出当天原材料交给外部 AI 撰写", "Review past reports, or export today's material for an external AI")}</p>
            </div>
          </div>
          <button className="act home-report-action" id="home-report-open" onClick={() => setView("report", true)}>
            {t("打开日报工作区", "Open report workspace")}
          </button>
        </section>

        {/* ---- recent records ---- */}
        <section className="home-panel home-recent">
          <div className="home-panel-head">
            <div className="home-panel-title">
              <h2>{t("最近记录", "Recent records")}</h2>
              <p id="home-recent-caption">
                {error || loading || !home
                  ? t("优先显示今天,今天为空时显示最近记录", "Shows today first, then your latest records")
                  : recentCaption}
              </p>
            </div>
            <button className="home-panel-link" onClick={() => setView("ledger", true)}>
              {t("查看全部", "View all")}
            </button>
          </div>
          <div id="recent" aria-live="polite">
            {error ? (
              <div className="home-error">
                <span>{t("最近记录暂时不可用。", "Recent records are temporarily unavailable.")}</span>
                <button className="act" onClick={() => void loadDash()}>
                  {t("重试", "Retry")}
                </button>
              </div>
            ) : loading || !home ? (
              <div className="home-error">
                <span>{t("正在载入最近记录…", "Loading recent records…")}</span>
              </div>
            ) : home.recent?.length ? (
              home.recent.map((card) => <RecordCard key={card.id} card={card} />)
            ) : (
              <div className="home-error">
                <span>{t("还没有可展示的记录。先在“设置 → 数据来源”完成配置,再同步一次。", "No records yet. Configure sources in Settings → Sources, then sync once.")}</span>
                <button className="act" onClick={() => setView("admin", true)}>
                  {t("配置来源", "Configure sources")}
                </button>
              </div>
            )}
          </div>
        </section>

        {/* ---- workspace status ---- */}
        <section className="home-panel home-workspace">
          <div className="home-panel-head">
            <div className="home-panel-title">
              <h2>{t("工作区状态", "Workspace status")}</h2>
              <p>{t("这里只显示摘要,详细配置仍在设置中", "Summary only; detailed configuration stays in Settings")}</p>
            </div>
          </div>
          <div className="home-status-list" id="home-workspace-status">
            <HomeStatusRow
              label={t("本地台账", "Local ledger")}
              value={home ? t(`${home.total_entries || 0} 条记录`, `${home.total_entries || 0} records`) : "…"}
            />
            <HomeStatusRow
              label={t("数据来源", "Data sources")}
              value={home ? `${home.active_sources || 0} / ${home.available_sources || 0}` : "…"}
              state={home ? (home.active_sources ? "" : "warn") : "off"}
            />
          </div>
          <div className="home-quick-actions">
            <button className="act" onClick={() => setView("ledger", true)}>
              {t("搜索台账", "Search ledger")}
            </button>
            <button className="act" onClick={() => setView("admin", true)}>
              {t("管理来源", "Manage sources")}
            </button>
          </div>
        </section>
      </div>
    </div>
  );
}
