// Daily report view for the loom serve admin console.
//
// No AI generation happens here (report synthesis is handed off to an external
// AI / Feishu agent). This view does two things:
//   1) lists historical daily reports already stored in the local ledger
//      (kind=="report", tool=="日报"), newest first, via the existing search;
//   2) exports a day's raw *material* (commits + sessions + assets) as markdown
//      the user can copy into their AI of choice — POST /api/admin/action
//      action=report_material.

import { useCallback, useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useLoom } from "@/runtime/LoomProvider";
import { RecordCard } from "@/components/RecordDrawer";
import { useT } from "@/lib/lang";
import type { LoomSearchHit } from "@/types/loom";

const REPORT_TOOL = "日报";

function localISODate(): string {
  const d = new Date();
  const off = d.getTimezoneOffset();
  return new Date(d.getTime() - off * 60000).toISOString().slice(0, 10);
}

type Notice = { text: string; kind: "" | "error" | "success" };

export function ReportView() {
  const t = useT();
  const { ledger } = useLoom();
  const client = ledger;

  const [date, setDate] = useState<string>(localISODate);
  const [message, setMessage] = useState<Notice | null>(null);

  // Historical daily reports (stored in the local ledger).
  const [reports, setReports] = useState<LoomSearchHit[]>([]);
  const [reportsLoading, setReportsLoading] = useState<boolean>(false);

  // Exported raw material for the selected day.
  const [material, setMaterial] = useState<string>("");
  const [exporting, setExporting] = useState<boolean>(false);
  const [syncing, setSyncing] = useState<boolean>(false);

  const loadReports = useCallback(async () => {
    setReportsLoading(true);
    try {
      const res = await client.search({ tool: REPORT_TOOL, page_size: 50 });
      setReports(res.hits);
    } catch {
      // keep the page usable even if history can't load
    } finally {
      setReportsLoading(false);
    }
  }, [client]);

  useEffect(() => {
    void loadReports();
  }, [loadReports]);

  const exportMaterial = useCallback(async () => {
    setExporting(true);
    setMessage(null);
    try {
      const r = await client.reportMaterial(date);
      if (!r.ok) {
        setMessage({ text: r.message || t("导出失败", "Export failed"), kind: "error" });
        return;
      }
      setMaterial(r.material || "");
      setMessage({
        text: t(
          "已导出当天原材料。复制到你的 AI 里写日报,写好后用 loom report set 存回台账。",
          "Material exported. Paste it into your AI to draft the report, then save it back with loom report set.",
        ),
        kind: "success",
      });
    } catch (e) {
      setMessage({ text: e instanceof Error && e.message ? e.message : String(e), kind: "error" });
    } finally {
      setExporting(false);
    }
  }, [client, date, t]);

  const syncNow = useCallback(async () => {
    if (syncing) return;
    setSyncing(true);
    setMessage(null);
    try {
      await client.adminAction({ action: "sync", source: "all", since: "", backup: false, push: false });
      void loadReports();
      setMessage({ text: t("同步完成。", "Sync completed."), kind: "success" });
    } catch (e) {
      setMessage({ text: e instanceof Error && e.message ? e.message : String(e), kind: "error" });
    } finally {
      setSyncing(false);
    }
  }, [client, syncing, t, loadReports]);

  const copyMaterial = useCallback(async () => {
    if (!material) return;
    try {
      await navigator.clipboard.writeText(material);
      setMessage({ text: t("原材料已复制到剪贴板。", "Material copied to the clipboard."), kind: "success" });
    } catch {
      setMessage({ text: t("无法访问剪贴板,请手动选择并复制。", "Clipboard is unavailable; please select and copy manually."), kind: "error" });
    }
  }, [material, t]);

  return (
    <>
      <div className="report-head">
        <div>
          <h1>{t("日报", "Daily report")}</h1>
          <p>
            {t(
              "查看已保存的历史日报,或导出某天的原材料交给外部 AI 撰写。Loom 不在本地生成日报。",
              "Review saved reports, or export a day's raw material for an external AI to draft. Loom does not generate reports locally.",
            )}
          </p>
        </div>
        <label className="report-date" htmlFor="report-date">
          <span>{t("日期", "Date")}</span>
          <input id="report-date" type="date" value={date} onChange={(e) => setDate(e.target.value || localISODate())} />
        </label>
      </div>

      <div className="report-layout">
        <section className="report-card">
          <div className="report-state-line">
            <div>
              <h2>{t("导出原材料", "Export material")}</h2>
              <p className="report-card-copy">
                {t(
                  "聚合当天的提交、AI 会话与数据/代码痕迹,生成一份可直接喂给 AI 的 Markdown。",
                  "Aggregates the day's commits, AI sessions, and data/code traces into markdown you can feed to an AI.",
                )}
              </p>
            </div>
          </div>

          <div className="credential-note">
            <i className="status-dot" />
            <span>
              {t(
                "原材料只在本地生成并展示;是否上传、交给谁写,由你决定。",
                "Material is generated and shown locally; you decide whether and where to send it.",
              )}
            </span>
          </div>

          <div className="report-actions">
            <button className="act primary" id="report-export" onClick={() => void exportMaterial()} disabled={exporting}>
              {exporting ? t("导出中…", "Exporting…") : t("导出当天原材料", "Export material")}
            </button>
            <button className="act" onClick={() => void syncNow()} disabled={syncing}>
              {syncing ? t("同步中…", "Syncing…") : t("先同步记录", "Sync records first")}
            </button>
          </div>

          {message ? (
            <div className={`notice ${message.kind}`.trimEnd()} id="report-message" aria-live="polite">
              <i className={`status-dot ${message.kind === "error" ? "error" : message.kind === "success" ? "" : "warn"}`.trimEnd()} />
              <span>{message.text}</span>
            </div>
          ) : null}

          {material ? (
            <div className="report-output" id="report-output">
              <label className="field" htmlFor="report-material">
                <span>{t("原材料(Markdown)", "Material (Markdown)")}</span>
              </label>
              <textarea id="report-material" spellCheck={false} value={material} onChange={(e) => setMaterial(e.target.value)} />
              <div className="loom-md">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{material}</ReactMarkdown>
              </div>
              <div className="report-actions">
                <button className="act" onClick={() => void copyMaterial()}>
                  {t("复制原材料", "Copy material")}
                </button>
              </div>
            </div>
          ) : null}
        </section>

        <aside className="report-card">
          <h2>{t("如何生成日报", "How reports are made")}</h2>
          <p className="report-card-copy">
            {t(
              "Loom 负责采集与整理,不内置 AI 写作。合成日报交给你的外部 AI 或飞书 agent。",
              "Loom collects and organizes; it has no built-in writing AI. Synthesis is handed to your external AI or Feishu agent.",
            )}
          </p>
          <div className="detail-list">
            <div className="detail-item">
              <span>{t("第 1 步", "Step 1")}</span>
              <b>{t("导出当天原材料", "Export material")}</b>
            </div>
            <div className="detail-item">
              <span>{t("第 2 步", "Step 2")}</span>
              <b>{t("交给 AI 写成日报", "Draft with your AI")}</b>
            </div>
            <div className="detail-item">
              <span>{t("第 3 步", "Step 3")}</span>
              <code>loom report set &lt;日期&gt; --file &lt;日报.md&gt;</code>
            </div>
          </div>
        </aside>
      </div>

      <section className="report-card">
        <div className="report-state-line">
          <div>
            <h2>{t("历史日报", "Past reports")}</h2>
            <p className="report-card-copy">
              {t(
                "已保存到本地台账的日报,最新在前;点任意一条查看完整内容。",
                "Reports saved to your local ledger, newest first; click any one to view its full content.",
              )}
            </p>
          </div>
          <span className="report-source-chip">
            <span>{t("历史日报", "Reports")}</span>
            <b>{reports.length}</b>
          </span>
        </div>

        {reportsLoading && !reports.length ? (
          <p className="report-card-copy">{t("正在载入历史日报…", "Loading past reports…")}</p>
        ) : reports.length ? (
          <div className="report-source-list">
            {reports.map((r) => (
              <RecordCard key={r.id} card={r} />
            ))}
          </div>
        ) : (
          <p className="report-card-copy">
            {t(
              "还没有历史日报。用 loom report set 保存后会显示在这里。",
              "No past reports yet. They appear here once you save one via loom report set.",
            )}
          </p>
        )}
      </section>
    </>
  );
}
