// Admin / Settings view for the loom serve console.
//
// Mirrors browse.html's #v-admin DOM + class names so browse.css styles it
// identically: sources list (icons + status + toggles), source-config modal
// (git repos / feishu bitables / generic scan dirs), sync options + results,
// knowledge backup (with risky-file warnings), a setup checklist, data &
// privacy boundary + storage, general preferences (profile / git identity /
// appearance), and loom-skill agent integrations. All data comes from the Loom
// client (adminOverview / adminAction / skillsStatus / installSkill /
// uninstallSkill / savePref) reached through useLoom().ledger.
//
// The chat/AI-direct/enterprise-gateway pieces of the former desktop app have
// been removed — this is a local, manual admin console.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLoom } from "@/runtime/LoomProvider";
import { useLang, useT, type Translate } from "@/lib/lang";
import { useTheme, type ThemePref } from "@/lib/theme";
import type { LoomCard, LoomSkillAgent, LoomSkillAgentKey } from "@/types/loom";

// ---------------------------------------------------------------------------
// icons — the subset of browse.html's icon() paths used by the admin view.
// ---------------------------------------------------------------------------
const ICON_PATHS: Record<string, string> = {
  sync: '<path d="M20 6v5h-5"/><path d="M4 18v-5h5"/><path d="M18.5 9A7 7 0 0 0 6.6 6.6L4 11M20 13l-2.6 4.4A7 7 0 0 1 5.5 15"/>',
  settings:
    '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06-2.83 2.83-.06-.06A1.7 1.7 0 0 0 15 19.4a1.7 1.7 0 0 0-1 .6 1.7 1.7 0 0 0-.4 1.1V21h-4v-.1A1.7 1.7 0 0 0 8.6 19.4a1.7 1.7 0 0 0-1.88.34l-.06.06-2.83-2.83.06-.06A1.7 1.7 0 0 0 4.6 15a1.7 1.7 0 0 0-.6-1 1.7 1.7 0 0 0-1.1-.4H3v-4h.1A1.7 1.7 0 0 0 4.6 8.6a1.7 1.7 0 0 0-.34-1.88l-.06-.06 2.83-2.83.06.06A1.7 1.7 0 0 0 9 4.6a1.7 1.7 0 0 0 1-.6 1.7 1.7 0 0 0 .4-1.1V3h4v.1A1.7 1.7 0 0 0 15.4 4.6a1.7 1.7 0 0 0 1.88-.34l.06-.06 2.83 2.83-.06.06A1.7 1.7 0 0 0 19.4 9c.12.4.33.75.6 1 .3.28.68.42 1.1.4h.1v4h-.1c-.42-.02-.8.12-1.1.4-.27.25-.48.6-.6 1Z"/>',
  trash: '<path d="M4 7h16M9 7V4h6v3m3 0-1 14H7L6 7m4 4v6m4-6v6"/>',
  close: '<path d="m6 6 12 12M18 6 6 18"/>',
  chevron: '<path d="m9 18 6-6-6-6"/>',
  check: '<path d="m5 13 4 4L19 7"/>',
  git: '<circle cx="6" cy="5" r="2"/><circle cx="18" cy="6" r="2"/><circle cx="6" cy="19" r="2"/><path d="M6 7v10m2-7c5 0 8-1 8-3"/>',
  feishu: '<rect x="4" y="4" width="16" height="16" rx="3"/><path d="M4 10h16M10 4v16"/>',
  shield: '<path d="M12 3 5 6v5c0 4.6 2.8 8 7 10 4.2-2 7-5.4 7-10V6z"/><path d="m9 12 2 2 4-4"/>',
  device: '<rect x="3" y="4" width="18" height="13" rx="2"/><path d="M8 21h8m-6-4-1 4m5-4 1 4"/>',
  cloud: '<path d="M7 18h11a4 4 0 0 0 .7-7.9A7 7 0 0 0 5.4 8.4 4.8 4.8 0 0 0 7 18Z"/><path d="m9 13 3-3 3 3m-3-3v7"/>',
  doc: '<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v5h5M9 12h6M9 16h6"/>',
  agent: '<rect x="4" y="5" width="16" height="14" rx="3"/><path d="m8 10 2 2-2 2m4 0h4"/>',
};

function Icon({ name }: { name: string }) {
  const path = ICON_PATHS[name] || '<circle cx="12" cy="12" r="8"/>';
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      dangerouslySetInnerHTML={{ __html: path }}
    />
  );
}

function fmtBytes(n: number): string {
  n = Number(n) || 0;
  if (n < 1024) return n + " B";
  const u = ["KB", "MB", "GB", "TB"];
  let i = -1;
  do {
    n /= 1024;
    i++;
  } while (n >= 1024 && i < u.length - 1);
  return n.toFixed(n >= 100 ? 0 : n >= 10 ? 1 : 2) + " " + u[i];
}
const pct = (n: number, max: number): number => (max ? Math.max(4, (100 * n) / max) : 0);

function sourceLabel(T: Translate, n: string): string {
  const map: Record<string, string> = {
    git: "Git",
    claude: "Claude",
    codex: "Codex",
    cursor: "Cursor",
    codebuddy: "CodeBuddy",
    feishu: T("飞书需求表", "Feishu Bitable"),
    docs: T("项目文档", "Project Docs"),
    notes: T("个人笔记", "Notes"),
    backup: T("知识库备份", "Knowledge backup"),
  };
  return map[n] || n;
}
function sourceIconName(n: string): string {
  return n === "git" ? "git" : n === "feishu" ? "feishu" : ["docs", "notes"].includes(n) ? "doc" : "agent";
}

// ---------------------------------------------------------------------------
// normalized data shapes (all optional; both the rich live overview and the
// thinner mock overview are accepted).
// ---------------------------------------------------------------------------
type Source = {
  name: string;
  enabled: boolean;
  available?: boolean;
  status?: string;
  message?: string;
  category?: string;
  checks?: { value?: string }[];
};
type Broken = { severity: string; title: string; detail: string; area: string };
type Vault = {
  dir?: string;
  git?: boolean;
  git_remotes?: string[];
  remote_config?: string;
  tracked_risky?: string[];
  gitignore?: { missing?: string[] };
  dirty?: boolean;
  dirty_count?: number;
};
type Repo = { path: string; git?: boolean; branch?: string; dirty_count?: number };
type Identities = { emails?: string[]; names?: string[] };
type Owner = { name?: string; feishu_name?: string };
type AdminConfig = { owner?: Owner; env_keys?: Record<string, string> };
type Bitable = { name: string; app_token: string; table_id: string };
type Collected = {
  entries?: number;
  date_start?: string;
  date_end?: string;
  index_ready?: boolean;
  tools?: Record<string, number>;
};
type AdminData = {
  sources: Source[];
  broken: Broken[];
  vault: Vault;
  repos: Repo[];
  identities: Identities;
  config: AdminConfig;
  feishu: { bitables: Bitable[] };
  collected: Collected;
};
type ConsoleData = {
  today_entries: number;
  active_sources: number;
  available_sources: number;
  local_bytes: number;
  recent: LoomCard[];
  summarized: number;
  classified: number;
};
type ResourceItem = { label: string; bytes: number };
type Overview = { admin: AdminData; console: ConsoleData; resources: ResourceItem[] };

type SyncSourceRow = { name: string; status: string; count?: number; message?: string };
type SyncData = { status?: string; sources?: SyncSourceRow[]; backup?: { ok?: boolean; message?: string } };
type BackupData = { ok?: boolean; message?: string };
type AdminActionResult = {
  ok?: boolean;
  status?: string;
  message?: string;
  output?: string;
  refresh?: boolean;
  overview?: unknown;
  needs_confirm?: string;
  sync?: SyncData;
  backup?: BackupData;
};

function normalizeOverview(raw: Record<string, unknown>): Overview {
  const r = raw as Record<string, unknown>;
  const a = ((r.admin as Record<string, unknown>) ?? r) as Record<string, unknown>;
  const sources = (a.sources as Source[]) ?? [];
  const vault = (a.vault as Vault) ?? {};
  const admin: AdminData = {
    sources,
    broken: (a.broken as Broken[]) ?? [],
    vault: {
      dir: vault.dir,
      git: vault.git,
      git_remotes: vault.git_remotes ?? [],
      remote_config: vault.remote_config,
      tracked_risky: vault.tracked_risky ?? [],
      gitignore: { missing: vault.gitignore?.missing ?? [] },
      dirty: vault.dirty,
      dirty_count: vault.dirty_count,
    },
    repos: (a.repos as Repo[]) ?? [],
    identities: (a.identities as Identities) ?? { emails: [], names: [] },
    config: (a.config as AdminConfig) ?? { owner: {}, env_keys: {} },
    feishu: (a.feishu as { bitables: Bitable[] }) ?? { bitables: [] },
    collected:
      (a.collected as Collected) ?? { tools: (a.tools as Record<string, number>) ?? {}, entries: 0 },
  };
  const availableCount = sources.filter((s) => s.available !== false).length;
  const console: ConsoleData = {
    today_entries: (r.today_entries as number) ?? 0,
    active_sources:
      (r.active_sources as number) ??
      sources.filter((s) => s.enabled && s.available !== false).length,
    available_sources: (r.available_sources as number) ?? availableCount,
    local_bytes: (r.local_bytes as number) ?? 0,
    recent: (r.recent as LoomCard[]) ?? (a.recent as LoomCard[]) ?? [],
    summarized: (r.summarized as number) ?? 0,
    classified: (r.classified as number) ?? 0,
  };
  const resources = ((r.resources as { items?: ResourceItem[] })?.items ?? []) as ResourceItem[];
  return { admin, console, resources };
}

type PaneName = "overview" | "onboarding" | "sources" | "privacy" | "settings";

// ===========================================================================
export function AdminView() {
  const T = useT();
  const { pref: langPref, setLang } = useLang();
  const { pref: themePref, setThemePref } = useTheme();
  const { ledger, openRecord } = useLoom();
  const client = ledger;

  const [loadState, setLoadState] = useState<"loading" | "ready" | "error">("loading");
  const [loadError, setLoadError] = useState<{ message: string; status?: number } | null>(null);
  const [data, setData] = useState<Overview | null>(null);
  const [pane, setPane] = useState<PaneName>("overview");

  // sync + backup panel state
  const [syncOptionsOpen, setSyncOptionsOpen] = useState(false);
  const [syncResult, setSyncResult] = useState<SyncData | null>(null);
  const [syncLog, setSyncLog] = useState<string>(T("等待同步", "Ready"));
  const [backupResult, setBackupResult] = useState<BackupData | null>(null);
  const [busy, setBusy] = useState(false);

  // form fields
  const [syncSource, setSyncSource] = useState("all");
  const [syncSince, setSyncSince] = useState("");
  const [syncBackupChecked, setSyncBackupChecked] = useState(true);
  const [syncPushChecked, setSyncPushChecked] = useState(false);
  const [repoPath, setRepoPath] = useState("");
  const [identityValue, setIdentityValue] = useState("");
  const [fsName, setFsName] = useState("");
  const [fsTable, setFsTable] = useState("");
  const [fsUrl, setFsUrl] = useState("");
  const [ownerName, setOwnerName] = useState("");
  const [ownerFeishu, setOwnerFeishu] = useState("");
  const [genericPath, setGenericPath] = useState("");
  const [prefsMsg, setPrefsMsg] = useState("");

  // ---- loom-skill hot-plug into AI agents ----
  const [skillAgents, setSkillAgents] = useState<LoomSkillAgent[] | null>(null);
  const [skillBusy, setSkillBusy] = useState<string>("");
  const [skillMsg, setSkillMsg] = useState<string>("");
  const [skillOk, setSkillOk] = useState<boolean>(true);

  // source-config modal
  const [configSource, setConfigSource] = useState<string>("");

  const admin = data?.admin;

  // ---- load overview ------------------------------------------------------
  const loadingRef = useRef(false);
  const loadAdmin = useCallback(async () => {
    if (loadingRef.current) return;
    loadingRef.current = true;
    setLoadState((prev) => (prev === "ready" ? "ready" : "loading"));
    setLoadError(null);
    try {
      const raw = (await client.adminOverview()) as unknown as Record<string, unknown>;
      const next = normalizeOverview(raw);
      setData(next);
      setOwnerName(next.admin.config.owner?.name || "");
      setOwnerFeishu(next.admin.config.owner?.feishu_name || "");
      setLoadState("ready");
    } catch (err) {
      const e = err as { message?: string; status?: number };
      setLoadError({ message: e?.message || T("加载失败", "Failed to load"), status: e?.status });
      setLoadState("error");
    } finally {
      loadingRef.current = false;
    }
  }, [client, T]);

  useEffect(() => {
    void loadAdmin();
  }, [loadAdmin]);

  // pull loom-skill install status per agent
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const r = await client.skillsStatus();
        if (!cancelled) setSkillAgents(r.agents || []);
      } catch {
        if (!cancelled) setSkillAgents(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [client]);

  // keep sync-source select valid against enabled sources
  const enabledSources = useMemo(
    () => (admin?.sources || []).filter((s) => s.enabled && s.available !== false),
    [admin],
  );
  useEffect(() => {
    if (syncSource !== "all" && !enabledSources.some((s) => s.name === syncSource)) {
      setSyncSource("all");
    }
  }, [enabledSources, syncSource]);

  // ---- admin action (sync / backup / config mutations) --------------------
  const runAdminAction = useCallback(
    async (payload: Record<string, unknown>, confirmWord?: string | null): Promise<AdminActionResult> => {
      if (confirmWord && !window.confirm(T(`确认执行 ${confirmWord}?`, `Confirm ${confirmWord}?`))) {
        return { ok: false, status: "error" };
      }
      if (confirmWord) payload.confirm = confirmWord;
      setBusy(true);
      if (payload.action === "sync") {
        setSyncResult(null);
        setSyncOptionsOpen(true);
      }
      setSyncLog(T("执行中…", "Running…"));
      try {
        let r = (await client.adminAction(payload)) as AdminActionResult;
        if (!r.ok && r.needs_confirm && window.confirm(r.message || "")) {
          payload.confirm = r.needs_confirm;
          r = (await client.adminAction(payload)) as AdminActionResult;
        }
        if (r.refresh || r.overview) await loadAdmin();
        if (payload.action === "sync") {
          setSyncResult(r.sync || { status: r.status || (r.ok ? "success" : "error"), sources: [] });
        }
        if (payload.action === "vault_backup" && r.backup) setBackupResult(r.backup);
        const st = r.status || (r.ok ? "success" : "error");
        const prefix = st === "partial" ? "⚠ " : st === "success" ? "✓ " : "✗ ";
        setSyncLog(prefix + (r.message || "") + (r.output ? "\n\n" + r.output : ""));
        return r;
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        if (payload.action === "sync") setSyncResult({ status: "error", sources: [] });
        setSyncLog("✗ " + message);
        return { ok: false, status: "error", message };
      } finally {
        setBusy(false);
      }
    },
    [client, loadAdmin, T],
  );

  // ---- individual actions -------------------------------------------------
  const runSync = () =>
    void runAdminAction(
      { action: "sync", source: syncSource, since: syncSince, backup: syncBackupChecked, push: syncPushChecked },
      syncPushChecked ? "push" : null,
    );
  const vaultBackup = (push: boolean) => void runAdminAction({ action: "vault_backup", push }, push ? "push" : null);
  const sourceSet = (name: string, enabled: boolean) => void runAdminAction({ action: "source_set", name, enabled });
  const repoRemove = (path: string) => void runAdminAction({ action: "repo_remove", path }, "remove");
  const identityRemove = (value: string) => void runAdminAction({ action: "identity_remove", value }, "remove");
  const identityAdd = () => {
    void runAdminAction({ action: "identity_add", value: identityValue });
    setIdentityValue("");
  };
  const ownerSet = () => void runAdminAction({ action: "owner_set", name: ownerName, feishu_name: ownerFeishu });
  const feishuAdd = () => {
    void runAdminAction({ action: "feishu_add", name: fsName, url: fsUrl, table_id: fsTable });
    setFsName("");
    setFsTable("");
    setFsUrl("");
  };
  const feishuRemove = (name: string) => void runAdminAction({ action: "feishu_remove", name }, "remove");
  const repoAdd = () => {
    void runAdminAction({ action: "repo_add", path: repoPath });
    setRepoPath("");
  };
  const sourcePathSet = (name: string) => void runAdminAction({ action: "source_path_set", name, path: genericPath });

  // ---- source config modal ------------------------------------------------
  const openSourceConfig = (name: string) => {
    setRepoPath("");
    const s = admin?.sources.find((x) => x.name === name);
    setGenericPath((s?.checks?.[0]?.value as string) || "");
    setConfigSource(name);
  };
  const closeSourceConfig = () => setConfigSource("");

  const showPane = (name: PaneName) => setPane(name);

  // ---- loom-skill install / uninstall per agent ---------------------------
  const toggleSkill = useCallback(
    async (agent: LoomSkillAgentKey, install: boolean) => {
      setSkillBusy(agent);
      setSkillMsg("");
      setSkillOk(true);
      try {
        const r = install ? await client.installSkill(agent) : await client.uninstallSkill(agent);
        setSkillAgents(r.agents || null);
        const first = r.results?.[0];
        setSkillOk(first?.ok ?? r.ok);
        if (first?.backup) {
          setSkillMsg(T(`已备份你的原文件 → ${first.backup}`, `Backed up your file → ${first.backup}`));
        } else if (first?.message) {
          setSkillMsg(first.message);
        }
      } catch (e) {
        setSkillOk(false);
        setSkillMsg(e instanceof Error ? e.message : String(e));
      } finally {
        setSkillBusy("");
      }
    },
    [client, T],
  );

  // ---- savePref (UI preferences → config.ui) ------------------------------
  const savePref = async (nextLang: string, nextTheme: string) => {
    try {
      const r = await client.savePref(nextLang, nextTheme);
      setPrefsMsg(r.ok ? T("已保存偏好", "Preferences saved") : r.message || T("保存失败", "Save failed"));
    } catch (e) {
      setPrefsMsg(e instanceof Error ? e.message : String(e));
    }
  };

  // =========================================================================
  const shellHidden = loadState !== "ready" && !data;
  const loadVisible = loadState !== "ready";
  const failed = loadState === "error";
  const expired = failed && loadError?.status === 403;

  return (
    <>
      <div className="admin-head">
        <div className="admin-title">
          <h1>{T("设置", "Settings")}</h1>
          <p>{T("管理数据来源、隐私、界面偏好与 AI 助手集成。", "Manage data sources, privacy, preferences, and agent integrations.")}</p>
        </div>
        <button
          className="icon-btn"
          id="admin-refresh"
          onClick={() => void loadAdmin()}
          disabled={loadState === "loading"}
          title={T("刷新", "Refresh")}
          aria-label={T("刷新", "Refresh")}
        >
          <Icon name="sync" />
        </button>
      </div>

      {loadVisible && (
        <div
          className={`admin-load-state${failed ? " is-error" : ""}`}
          id="admin-load-state"
          role="status"
          aria-live="polite"
          aria-busy={failed ? "false" : "true"}
        >
          <span className="admin-load-mark" id="admin-load-mark">
            {failed ? <Icon name="close" /> : <span className="admin-spinner" aria-hidden="true" />}
          </span>
          <div className="admin-load-copy">
            <strong>
              {failed
                ? expired
                  ? T("管理会话已失效", "Admin session expired")
                  : T("管理页暂时无法载入", "Admin page could not load")
                : data
                  ? T("正在刷新管理信息", "Refreshing admin information")
                  : T("正在载入管理信息", "Loading admin information")}
            </strong>
            <span>
              {failed
                ? expired
                  ? T(
                      "请从 loom serve 终端输出的最新地址重新打开;仅刷新当前页面无法恢复会话。",
                      "Reopen the latest URL printed by loom serve; refreshing this page cannot restore the session.",
                    )
                  : loadError?.message || T("请确认 loom serve 仍在运行,然后重试。", "Make sure loom serve is running, then retry.")
                : data
                  ? T("当前内容仍可查看,完成后会自动更新。", "Current content remains available and will update automatically.")
                  : T("正在读取数据来源、同步状态和存储信息…", "Reading data sources, sync status, and storage…")}
            </span>
          </div>
          <button className="act" id="admin-load-retry" onClick={() => void loadAdmin()} hidden={!failed}>
            {T("重试", "Retry")}
          </button>
        </div>
      )}

      {!shellHidden && admin && data && (
        <div className="admin-shell" id="admin-shell">
          <div className="admin-tabs" role="tablist" aria-label={T("管理分区", "Admin sections")}>
            {(
              [
                ["overview", T("概览", "Overview")],
                ["onboarding", T("开始使用", "Get started")],
                ["sources", T("数据来源", "Sources")],
                ["privacy", T("数据与隐私", "Data & Privacy")],
                ["settings", T("通用", "General")],
              ] as [PaneName, string][]
            ).map(([name, label]) => (
              <button
                key={name}
                data-admin-pane={name}
                className={pane === name ? "on" : undefined}
                onClick={() => showPane(name)}
              >
                {label}
              </button>
            ))}
          </div>

          <div className="admin-workspace">
            {/* ---- onboarding pane (static setup checklist) ---- */}
            <div className={`admin-pane${pane === "onboarding" ? " on" : ""}`} id="admin-pane-onboarding">
              <div className="admin-grid">
                <section className="panel manual-panel">
                  <h3>{T("Loom 设置进度", "Loom setup progress")}</h3>
                  <div className="sub">
                    {T(
                      "根据当前配置推断的清单;逐项完成即可让 Loom 稳定采集与整理。不涉及任何自动写入或上传。",
                      "A checklist inferred from your current configuration; complete each item for reliable collection. Nothing here writes or uploads automatically.",
                    )}
                  </div>
                  <SetupChecklist admin={admin} console={data.console} onGoto={showPane} />
                </section>
              </div>
            </div>

            {/* ---- overview pane (sync center) ---- */}
            <div className={`admin-pane${pane === "overview" ? " on" : ""}`} id="admin-pane-overview">
              <div className="admin-top" id="admin-answers">
                <Answers admin={admin} console={data.console} />
              </div>
              <section className="sync-card" id="admin-bridge">
                <span className="sync-icon">
                  <Icon name="sync" />
                </span>
                <div className="sync-card-copy">
                  <strong>{T("数据同步", "Data sync")}</strong>
                  <span>{T("从已开启的来源更新本地台账、检索索引和日记。", "Update the local ledger, search index, and journal from enabled sources.")}</span>
                </div>
                <div className="sync-actions">
                  <button className="act primary" onClick={runSync} disabled={busy}>
                    {T("同步", "Sync")}
                  </button>
                  <button
                    className="icon-btn"
                    id="sync-options-btn"
                    onClick={() => setSyncOptionsOpen((v) => !v)}
                    title={T("同步设置", "Sync settings")}
                    aria-label={T("同步设置", "Sync settings")}
                    aria-expanded={syncOptionsOpen ? "true" : "false"}
                  >
                    <Icon name="settings" />
                  </button>
                </div>
              </section>
              <div className="sync-options" id="sync-options" hidden={!syncOptionsOpen}>
                <div className="sync-form">
                  <div className="sync-line">
                    <label className="field" htmlFor="sync-source">
                      <span>{T("数据来源", "Source")}</span>
                      <select id="sync-source" value={syncSource} onChange={(e) => setSyncSource(e.target.value)}>
                        <option value="all">all</option>
                        {enabledSources.map((s) => (
                          <option key={s.name} value={s.name}>
                            {s.name}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="field" htmlFor="sync-since">
                      <span>{T("开始日期", "Start date")}</span>
                      <input id="sync-since" type="date" title="since" autoComplete="off" value={syncSince} onChange={(e) => setSyncSince(e.target.value)} />
                    </label>
                  </div>
                  <div className="toggle-line">
                    <label className="checkline">
                      <input type="checkbox" checked={syncBackupChecked} onChange={(e) => setSyncBackupChecked(e.target.checked)} />{" "}
                      <span>{T("同步后备份", "Backup after sync")}</span>
                    </label>
                    <label className="checkline">
                      <input type="checkbox" checked={syncPushChecked} onChange={(e) => setSyncPushChecked(e.target.checked)} />{" "}
                      <span>{T("同步后推送", "Push after sync")}</span>
                    </label>
                  </div>
                </div>
                <SyncResult sync={syncResult} />
                <pre className="log" id="admin-log" aria-live="polite">
                  {syncLog}
                </pre>
              </div>
              <div className="admin-grid">
                <section className="panel manual-panel recent-admin">
                  <h3>{T("最近记录", "Recent records")}</h3>
                  <div id="admin-recent">
                    {data.console.recent.length ? (
                      data.console.recent.slice(0, 5).map((r) => (
                        <div className="row" key={r.id}>
                          <div>
                            <strong>{r.summary}</strong>
                            <div>
                              {r.date} · {r.project || "-"} · {r.tool || "-"}
                            </div>
                          </div>
                          <button className="icon-btn" onClick={() => openRecord(r.id)} title={T("查看", "View")} aria-label={T("查看", "View")}>
                            <Icon name="chevron" />
                          </button>
                        </div>
                      ))
                    ) : (
                      <div className="empty">{T("今天还没有新记录", "No new records today")}</div>
                    )}
                  </div>
                </section>
                {admin.broken.length > 0 && (
                  <section className="panel manual-panel" id="admin-broken-panel">
                    <h3>{T("待处理", "Needs attention")}</h3>
                    <div id="admin-broken">
                      {admin.broken.map((x, i) => (
                        <div className="row" key={i}>
                          <div>
                            <span className={`pill ${x.severity === "error" ? "error" : "warn"}`}>{x.severity}</span>
                            <strong>{x.title}</strong>
                            <div>
                              <code>
                                {x.area} · {x.detail}
                              </code>
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  </section>
                )}
              </div>
            </div>

            {/* ---- sources pane ---- */}
            <div className={`admin-pane${pane === "sources" ? " on" : ""}`} id="admin-pane-sources">
              <div className="admin-grid">
                <section className="panel manual-panel">
                  <h3>{T("数据来源", "Data sources")}</h3>
                  <div className="sub">
                    {T("按用途管理 Loom 记录的信息。暂停来源不会删除已有记录。", "Manage what Loom records by purpose. Pausing a source keeps existing records.")}
                  </div>
                  <div id="admin-sources" className="source-groups">
                    <SourceGroups sources={admin.sources} busy={busy} onToggle={sourceSet} onConfig={openSourceConfig} />
                  </div>
                </section>
              </div>
            </div>

            {/* ---- privacy pane ---- */}
            <div className={`admin-pane${pane === "privacy" ? " on" : ""}`} id="admin-pane-privacy">
              <div className="admin-grid">
                <section className="panel manual-panel">
                  <h3>{T("数据边界", "Data boundary")}</h3>
                  <div className="sub">{T("Loom 默认只同步整理后的工作信息,原始内容留在本地。", "Loom syncs structured work information; raw content stays local.")}</div>
                  <div id="admin-privacy">
                    <PrivacyBoundary />
                  </div>
                </section>
                <section className="panel privacy-metric-panel">
                  <h3>{T("存储用量", "Storage")}</h3>
                  <div id="admin-resources">
                    <Resources items={data.resources} />
                  </div>
                </section>
                <section className="panel privacy-metric-panel">
                  <h3>{T("数据概览", "Data overview")}</h3>
                  <div id="admin-collected">
                    <Collected collected={admin.collected} />
                  </div>
                </section>
                <section className="panel manual-panel">
                  <h3>{T("知识库备份", "Knowledge backup")}</h3>
                  <div className="sub">
                    {T("仅备份日记和知识文档,不包含密钥、索引和原始文件。", "Backs up journal and knowledge documents only, excluding secrets, indexes, and raw files.")}
                  </div>
                  <div id="admin-cloud">
                    <Backup vault={admin.vault} backupResult={backupResult} busy={busy} onBackup={vaultBackup} />
                  </div>
                </section>
              </div>
            </div>

            {/* ---- settings pane ---- */}
            <div className={`admin-pane${pane === "settings" ? " on" : ""}`} id="admin-pane-settings">
              <div className="admin-grid">
                <section className="panel manual-panel">
                  <h3>{T("个人信息", "Profile")}</h3>
                  <div className="sub">{T("用于日报署名和飞书中的人员匹配。", "Used for report attribution and Feishu matching.")}</div>
                  <div id="admin-owner">
                    <div className="owner-form">
                      <label className="field" htmlFor="owner-name">
                        <span>{T("姓名", "Name")}</span>
                        <input id="owner-name" autoComplete="off" spellCheck={false} value={ownerName} onChange={(e) => setOwnerName(e.target.value)} />
                      </label>
                      <label className="field" htmlFor="owner-feishu">
                        <span>{T("飞书显示名称", "Feishu display name")}</span>
                        <input id="owner-feishu" autoComplete="off" spellCheck={false} value={ownerFeishu} onChange={(e) => setOwnerFeishu(e.target.value)} />
                      </label>
                      <button className="act primary" onClick={ownerSet} disabled={busy}>
                        {T("保存", "Save")}
                      </button>
                    </div>
                  </div>
                </section>
                <section className="panel manual-panel">
                  <h3>{T("Git 身份识别", "Git identity")}</h3>
                  <div className="sub">
                    {T("添加你在 Git 提交中使用的姓名或邮箱,只采集与你匹配的提交。", "Add names or emails used in Git commits; only matching commits are collected.")}
                  </div>
                  <div className="identity-add">
                    <label className="field" htmlFor="identity-value">
                      <span>{T("姓名或邮箱", "Name or email")}</span>
                      <input id="identity-value" autoComplete="off" spellCheck={false} placeholder="name@example.com" value={identityValue} onChange={(e) => setIdentityValue(e.target.value)} />
                    </label>
                    <button className="act primary" onClick={identityAdd} disabled={busy}>
                      {T("添加", "Add")}
                    </button>
                  </div>
                  <div id="admin-identities">
                    <IdentityGroups identities={admin.identities} onRemove={identityRemove} />
                  </div>
                </section>
                <section className="panel manual-panel">
                  <h3>{T("界面偏好", "Appearance")}</h3>
                  <div className="sub">{T("默认跟随系统语言和明暗模式。", "Uses your system language and color scheme by default.")}</div>
                  <div className="preference-row">
                    <label className="field" htmlFor="language-select">
                      <span>{T("界面语言", "Language")}</span>
                      <select
                        id="language-select"
                        value={langPref}
                        onChange={(e) => {
                          const value = e.target.value as "system" | "zh" | "en";
                          setLang(value);
                          void savePref(value, themePref);
                        }}
                      >
                        <option value="system">{T("跟随系统", "System default")}</option>
                        <option value="zh">简体中文</option>
                        <option value="en">English</option>
                      </select>
                    </label>
                    <label className="field" htmlFor="theme-select">
                      <span>{T("外观", "Theme")}</span>
                      <select
                        id="theme-select"
                        value={themePref}
                        onChange={(e) => {
                          const value = e.target.value as ThemePref;
                          setThemePref(value);
                          void savePref(langPref, value);
                        }}
                      >
                        <option value="system">{T("跟随系统", "System default")}</option>
                        <option value="light">{T("亮色", "Light")}</option>
                        <option value="dark">{T("暗色", "Dark")}</option>
                      </select>
                    </label>
                    <div className="preference-hint">
                      {prefsMsg || T("偏好设置只影响界面,不改变采集内容。", "Appearance preferences do not change collected data.")}
                    </div>
                  </div>
                </section>
                <section className="panel manual-panel">
                  <h3>{T("AI 助手集成", "Agent integrations")}</h3>
                  <div className="sub">
                    {T(
                      "把 loom 技能一键装进你的 AI 助手,它们就知道何时该用 loom 查历史、记录、生成日报。可随时移除,只改 loom 自己的文件。",
                      "Install the loom skill into your AI agents so they know when to use loom to search history, record work, and draft reports. Removable anytime — only loom's own files are touched.",
                    )}
                  </div>
                  {(skillAgents || []).map((a) => {
                    const on = a.status === "installed" || a.status === "update_available" || a.status === "drifted";
                    const warn = a.status === "drifted" || a.status === "missing" || a.status === "foreign";
                    const pillClass =
                      a.status === "installed" ? "ok" : a.status === "update_available" ? "warn" : warn ? "error" : "off";
                    const pill =
                      a.status === "installed"
                        ? T("已安装", "Installed")
                        : a.status === "update_available"
                          ? T("有更新", "Update available")
                          : a.status === "drifted"
                            ? T("⚠ 被你改过", "⚠ Modified by you")
                            : a.status === "missing"
                              ? T("⚠ 文件缺失", "⚠ File missing")
                              : a.status === "foreign"
                                ? T("⚠ 非 loom 内容", "⚠ Non-loom content")
                                : T("未安装", "Not installed");
                    const rowBusy = skillBusy === a.agent;
                    return (
                      <div className="backup-overview" key={a.agent}>
                        <span className="source-icon">
                          <Icon name="agent" />
                        </span>
                        <div className="backup-copy">
                          <strong>
                            {a.label} <span className={`pill ${pillClass}`}>{pill}</span>
                            {!a.present && <span className="pill off">{T("未检测到", "Not detected")}</span>}
                          </strong>
                          <span>{a.target}</span>
                        </div>
                        <div className="backup-actions">
                          {on ? (
                            <button className="act" onClick={() => void toggleSkill(a.agent, false)} disabled={rowBusy}>
                              {rowBusy ? T("处理中…", "Working…") : T("移除", "Remove")}
                            </button>
                          ) : (
                            <button className="act primary" onClick={() => void toggleSkill(a.agent, true)} disabled={rowBusy}>
                              {rowBusy ? T("安装中…", "Installing…") : T("安装", "Install")}
                            </button>
                          )}
                        </div>
                      </div>
                    );
                  })}
                  {skillAgents === null && <div className="sub">{T("正在读取安装状态…", "Loading status…")}</div>}
                  {skillMsg && (
                    <div className={`notice ${skillOk ? "success" : "error"}`} aria-live="polite">
                      <i className={`status-dot ${skillOk ? "" : "error"}`} />
                      <span>{skillMsg}</span>
                    </div>
                  )}
                </section>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ---- source config modal ---- */}
      {admin && (
        <SourceConfigModal
          name={configSource}
          admin={admin}
          busy={busy}
          repoPath={repoPath}
          setRepoPath={setRepoPath}
          genericPath={genericPath}
          setGenericPath={setGenericPath}
          fsName={fsName}
          setFsName={setFsName}
          fsTable={fsTable}
          setFsTable={setFsTable}
          fsUrl={fsUrl}
          setFsUrl={setFsUrl}
          onClose={closeSourceConfig}
          onRepoAdd={repoAdd}
          onRepoRemove={repoRemove}
          onFeishuAdd={feishuAdd}
          onFeishuRemove={feishuRemove}
          onSourcePathSet={sourcePathSet}
          onOpenSource={openSourceConfig}
        />
      )}
    </>
  );
}

// ===========================================================================
// sub-components
// ===========================================================================
function Answers({ admin, console }: { admin: AdminData; console: ConsoleData }) {
  const T = useT();
  const bad = admin.broken.filter((x) => x.severity === "error").length;
  const warn = admin.broken.filter((x) => x.severity !== "error").length;
  const unavailableCount = admin.sources.filter((s) => s.available === false).length;
  const availableCount = admin.sources.filter((s) => s.available !== false).length;
  const cloudBad = (admin.vault.tracked_risky || []).length;
  const cloudWarn = (admin.vault.gitignore?.missing || []).length || !admin.vault.git;
  const toolKeys = Object.keys(admin.collected.tools || {}).length;
  return (
    <>
      <div className="answer ok">
        <h2>{T("今日记录", "Today")}</h2>
        <div className="big">{console.today_entries.toLocaleString()}</div>
        <div className="desc">
          {T("已摘要", "Summarized")} {console.summarized} · {T("已归类", "Classified")} {console.classified}
        </div>
      </div>
      <div className="answer ok">
        <h2>{T("数据来源", "Data sources")}</h2>
        <div className="big">
          {console.active_sources} / {console.available_sources ?? availableCount}
        </div>
        <div className="desc">
          {toolKeys}
          {T(" 个来源已有记录", " sources contain records")}
          {unavailableCount ? ` · ${unavailableCount}${T(" 个暂不可用", " unavailable")}` : ""}
        </div>
      </div>
      <div className={`answer ${bad ? "bad" : warn ? "warn" : "ok"}`}>
        <h2>{T("待处理", "Needs attention")}</h2>
        <div className="big">{bad + warn}</div>
        <div className="desc">{admin.broken[0] ? `${admin.broken[0].title} · ${admin.broken[0].detail}` : T("一切正常", "Everything looks good")}</div>
      </div>
      <div className={`answer ${cloudBad ? "bad" : cloudWarn ? "warn" : "ok"}`}>
        <h2>{T("本地占用", "Local storage")}</h2>
        <div className="big">{fmtBytes(console.local_bytes)}</div>
        <div className="desc">{T("记录、检索索引和知识文档", "Records, search index, and knowledge docs")}</div>
      </div>
    </>
  );
}

// A read-only setup checklist inferred from the admin overview — no AI, no
// automatic writes. Each item just links to the relevant pane.
function SetupChecklist({
  admin,
  console,
  onGoto,
}: {
  admin: AdminData;
  console: ConsoleData;
  onGoto: (pane: PaneName) => void;
}) {
  const T = useT();
  const idCount = (admin.identities.emails?.length || 0) + (admin.identities.names?.length || 0);
  const remoteReady = (admin.vault.git_remotes || []).length > 0 || !!admin.vault.remote_config;
  const items: { done: boolean; title: string; detail: string; pane: PaneName }[] = [
    {
      done: console.active_sources > 0,
      title: T("开启数据来源", "Enable data sources"),
      detail: T(`已开启 ${console.active_sources} / ${console.available_sources} 个来源`, `${console.active_sources} / ${console.available_sources} sources enabled`),
      pane: "sources",
    },
    {
      done: idCount > 0,
      title: T("配置 Git 身份", "Configure Git identity"),
      detail: idCount ? T(`已添加 ${idCount} 个身份`, `${idCount} identities added`) : T("尚未添加姓名/邮箱", "No name/email added yet"),
      pane: "settings",
    },
    {
      done: (admin.collected.entries || 0) > 0,
      title: T("完成首次同步", "Run the first sync"),
      detail: T(`台账共 ${(admin.collected.entries || 0).toLocaleString()} 条记录`, `${(admin.collected.entries || 0).toLocaleString()} records in the ledger`),
      pane: "overview",
    },
    {
      done: !!admin.collected.index_ready,
      title: T("检索索引就绪", "Search index ready"),
      detail: admin.collected.index_ready ? T("索引可用", "Index is up to date") : T("需要重建索引(同步一次即可)", "Index needs a rebuild (sync once)"),
      pane: "overview",
    },
    {
      done: !!admin.vault.git && remoteReady,
      title: T("配置知识库备份", "Configure knowledge backup"),
      detail: admin.vault.git ? (remoteReady ? T("已配置远程仓库", "Remote repository configured") : T("已初始化,未配置远程", "Initialized; no remote yet")) : T("知识库尚未初始化 Git", "Vault Git not initialized"),
      pane: "privacy",
    },
  ];
  const completed = items.filter((x) => x.done).length;
  return (
    <>
      <div className="onboarding-overview">
        <span className="onboarding-progress">
          {completed}/{items.length}
        </span>
        <div className="onboarding-overview-copy">
          <strong>{completed === items.length ? T("基础设置已经完成", "Core setup is complete") : T("从任意环节继续", "Continue from any area")}</strong>
          <span>{T("清单只反映当前配置状态,不会自动执行任何操作。", "The checklist reflects your current configuration; it never runs anything on its own.")}</span>
        </div>
      </div>
      <div className="onboarding-grid">
        {items.map((item) => (
          <article className={`onboarding-step ${item.done ? "done" : ""}`} key={item.title}>
            <span className="onboarding-step-mark">
              <Icon name={item.done ? "check" : "chevron"} />
            </span>
            <div className="onboarding-step-copy">
              <strong>{item.title}</strong>
              <span>{item.detail}</span>
              <button className="act" type="button" onClick={() => onGoto(item.pane)}>
                {item.done ? T("查看", "Review") : T("去设置", "Set up")}
              </button>
            </div>
          </article>
        ))}
      </div>
    </>
  );
}

function SourceCard({
  s,
  busy,
  onToggle,
  onConfig,
}: {
  s: Source;
  busy: boolean;
  onToggle: (name: string, enabled: boolean) => void;
  onConfig: (name: string) => void;
}) {
  const T = useT();
  const unavailable = s.available === false;
  const state = unavailable ? "off" : !s.enabled ? "off" : s.status === "error" ? "error" : s.status === "warn" ? "warn" : "ok";
  const stateText = unavailable
    ? T("暂不支持", "Unavailable")
    : !s.enabled
      ? T("已暂停", "Paused")
      : state === "error"
        ? T("需要处理", "Needs attention")
        : state === "warn"
          ? T("请检查", "Check")
          : T("正常", "Normal");
  const switchLabel = s.enabled
    ? T(`暂停 ${sourceLabel(T, s.name)}`, `Pause ${sourceLabel(T, s.name)}`)
    : T(`开启 ${sourceLabel(T, s.name)}`, `Enable ${sourceLabel(T, s.name)}`);
  return (
    <article className="source-tile">
      <div className="source-head">
        <div className="source-identity">
          <span className="source-icon">
            <Icon name={sourceIconName(s.name)} />
          </span>
          <strong>{sourceLabel(T, s.name)}</strong>
        </div>
        {!unavailable && (
          <button
            className="switch"
            role="switch"
            aria-checked={s.enabled ? "true" : "false"}
            aria-label={switchLabel}
            title={switchLabel}
            disabled={busy}
            onClick={() => onToggle(s.name, !s.enabled)}
          >
            <span />
          </button>
        )}
      </div>
      <p className="source-meta">{s.message}</p>
      <div className="source-actions">
        <span className="source-state">
          <i className={`status-dot ${state}`} />
          {stateText}
        </span>
        <button className="act source-config-btn" onClick={() => onConfig(s.name)}>
          <Icon name="settings" />
          {unavailable ? T("详情", "Details") : T("配置", "Configure")}
        </button>
      </div>
    </article>
  );
}

function SourceGroups({
  sources,
  busy,
  onToggle,
  onConfig,
}: {
  sources: Source[];
  busy: boolean;
  onToggle: (name: string, enabled: boolean) => void;
  onConfig: (name: string) => void;
}) {
  const T = useT();
  const meta: Record<string, [string, string]> = {
    development: [T("代码与 AI", "Code & AI"), T("代码提交与 AI 编程会话", "Code commits and AI coding sessions")],
    collaboration: [T("业务协作", "Collaboration"), T("团队任务、需求与协作平台", "Team tasks, requirements, and collaboration tools")],
    knowledge: [T("文件与知识", "Files & knowledge"), T("本地文档、笔记与知识资料", "Local documents, notes, and knowledge")],
    other: [T("其他来源", "Other sources"), T("尚未分类的数据来源", "Uncategorized data sources")],
  };
  const grouped: Record<string, Source[]> = {};
  (sources || []).forEach((s) => {
    const cat = s.category || "other";
    (grouped[cat] ??= []).push(s);
  });
  const order = ["development", "collaboration", "knowledge", "other"].filter((k) => (grouped[k] || []).length);
  return (
    <>
      {order.map((k) => {
        const rows = grouped[k];
        const m = meta[k];
        return (
          <section className="source-group" data-source-category={k} key={k}>
            <div className="source-group-head">
              <div className="source-group-title">
                <h4>{m[0]}</h4>
                <p>{m[1]}</p>
              </div>
              <span className="source-group-count">
                {rows.length} {T("个来源", rows.length === 1 ? "source" : "sources")}
              </span>
            </div>
            <div className="source-cards">
              {rows.map((s) => (
                <SourceCard key={s.name} s={s} busy={busy} onToggle={onToggle} onConfig={onConfig} />
              ))}
            </div>
          </section>
        );
      })}
    </>
  );
}

function SyncResult({ sync }: { sync: SyncData | null }) {
  const T = useT();
  if (!sync) return <div className="sync-result" id="sync-result" hidden aria-live="polite" />;
  const status = ["success", "partial", "error"].includes(sync.status || "") ? sync.status! : "error";
  const rows = sync.sources || [];
  const counts: Record<string, number> = { success: 0, partial: 0, error: 0 };
  rows.forEach((r) => (counts[r.status] = (counts[r.status] || 0) + 1));
  const title = status === "success" ? T("同步成功", "Sync completed") : status === "partial" ? T("同步部分完成", "Sync partially completed") : T("同步失败", "Sync failed");
  const backup = sync.backup;
  const backupStatus = backup ? (backup.ok ? "success" : "error") : "";
  const summary = [
    counts.success ? `${counts.success} ${T("成功", "succeeded")}` : "",
    counts.partial ? `${counts.partial} ${T("部分完成", "partial")}` : "",
    counts.error ? `${counts.error} ${T("失败", "failed")}` : "",
    backup ? T(backup.ok ? "备份成功" : "备份失败", backup.ok ? "backup succeeded" : "backup failed") : "",
  ]
    .filter(Boolean)
    .join(" · ");
  const dot = status === "partial" ? "warn" : status === "error" ? "error" : "";
  return (
    <div className={`sync-result ${status}`} id="sync-result" aria-live="polite">
      <div className="sync-result-head">
        <div className="sync-result-title">
          <i className={`status-dot ${dot}`} />
          <strong>{title}</strong>
        </div>
        <span className="sync-result-count">{summary || T("未执行来源", "No source ran")}</span>
      </div>
      <div className="sync-result-list">
        {rows.map((r, i) => {
          const rd = r.status === "partial" ? "warn" : r.status === "error" ? "error" : "";
          const detail =
            r.status === "success"
              ? `${r.count || 0} ${T("条", "records")}`
              : [r.count ? `${r.count} ${T("条", "records")}` : "", r.message || T("未知错误", "Unknown error")].filter(Boolean).join(" · ");
          return (
            <div className="sync-result-row" key={i}>
              <span className="sync-result-source">
                <i className={`status-dot ${rd}`} />
                {sourceLabel(T, r.name)}
              </span>
              <span className="sync-result-detail">{detail}</span>
            </div>
          );
        })}
        {backup && (
          <div className="sync-result-row">
            <span className="sync-result-source">
              <i className={`status-dot ${backupStatus === "error" ? "error" : ""}`} />
              {sourceLabel(T, "backup")}
            </span>
            <span className="sync-result-detail">{backup.message || T(backup.ok ? "备份完成" : "备份失败", backup.ok ? "Backup completed" : "Backup failed")}</span>
          </div>
        )}
      </div>
    </div>
  );
}

function Backup({
  vault,
  backupResult,
  busy,
  onBackup,
}: {
  vault: Vault;
  backupResult: BackupData | null;
  busy: boolean;
  onBackup: (push: boolean) => void;
}) {
  const T = useT();
  const remoteReady = (vault.git_remotes || []).length > 0 || !!vault.remote_config;
  const backupReady = vault.git && remoteReady;
  const cloudBad = (vault.tracked_risky || []).length;
  const cloudWarn = (vault.gitignore?.missing || []).length || !vault.git;
  return (
    <>
      <div className="backup-overview">
        <span className="source-icon">
          <Icon name="cloud" />
        </span>
        <div className="backup-copy">
          <strong>{backupReady ? T("备份已就绪", "Backup ready") : T("需要配置远程仓库", "Remote repository required")}</strong>
          <span>
            {vault.dirty
              ? `${vault.dirty_count}${T(" 项更改等待备份", " changes waiting to be backed up")}`
              : T("知识库已是最新状态", "Knowledge base is up to date")}
          </span>
        </div>
        <div className="backup-actions">
          <button className="act" onClick={() => onBackup(false)} disabled={busy}>
            {T("本地备份", "Local backup")}
          </button>
          <button className="act primary" onClick={() => onBackup(true)} disabled={busy}>
            {T("备份并推送", "Backup & Push")}
          </button>
        </div>
      </div>
      {backupResult && (
        <div className={`notice ${backupResult.ok ? "success" : "error"}`} id="backup-result" aria-live="polite">
          <i className={`status-dot ${backupResult.ok ? "" : "error"}`} />
          <span>{backupResult.message || T(backupResult.ok ? "备份完成" : "备份失败", backupResult.ok ? "Backup completed" : "Backup failed")}</span>
        </div>
      )}
      {(cloudBad || cloudWarn) && (
        <div className="notice">
          <i className="status-dot warn" />
          <span>
            {cloudBad
              ? T("发现可能不应进入云端的文件,请先查看详情。", "Potentially sensitive tracked files found; review details first.")
              : T("备份忽略规则尚未完整配置。", "Backup ignore rules are incomplete.")}
          </span>
        </div>
      )}
      <details className="admin-disclosure">
        <summary>{T("查看技术详情", "View technical details")}</summary>
        <div className="detail-list">
          <div className="detail-item">
            <span>{T("知识库目录", "Knowledge directory")}</span>
            <code>{vault.dir}</code>
          </div>
          <div className="detail-item">
            <span>{T("Git 状态", "Git status")}</span>
            <b>{vault.git ? T("已初始化", "Initialized") : T("未初始化", "Not initialized")}</b>
          </div>
          <div className="detail-item">
            <span>{T("远程仓库", "Remote")}</span>
            <code>{(vault.git_remotes || [])[0] || vault.remote_config || T("未配置", "Not configured")}</code>
          </div>
          <div className="detail-item">
            <span>{T("风险文件", "Risky files")}</span>
            <code>{(vault.tracked_risky || []).join(", ") || T("无", "None")}</code>
          </div>
        </div>
      </details>
    </>
  );
}

function Collected({ collected }: { collected: Collected }) {
  const T = useT();
  const tools = collected.tools || {};
  const entries = Object.entries(tools);
  const max = Math.max(1, ...entries.map((x) => x[1]));
  return (
    <>
      <div className="data-summary">
        <div className="data-stat">
          <b>{(collected.entries || 0).toLocaleString()}</b>
          <span>{T("记录总数", "Total records")}</span>
        </div>
        <div className="data-stat">
          <b>
            {(collected.date_start || "-").slice(0, 4)}–{(collected.date_end || "-").slice(0, 4)}
          </b>
          <span>{T("时间范围", "Date range")}</span>
        </div>
        <div className="data-stat">
          <b>{collected.index_ready ? T("正常", "Ready") : T("需重建", "Rebuild")}</b>
          <span>{T("搜索索引", "Search index")}</span>
        </div>
        <div className="data-stat">
          <b>{entries.length}</b>
          <span>{T("已有记录的来源", "Sources with records")}</span>
        </div>
      </div>
      <div className="admin-breakdown">
        <div className="admin-breakdown-label">{T("来源分布", "Source breakdown")}</div>
        {entries.length ? (
          entries.slice(0, 8).map(([k, n]) => (
            <div className="barline" key={k}>
              <span className="nm2" title={k}>
                {k}
              </span>
              <span className="track">
                <i style={{ width: `${pct(n, max)}%` }} />
              </span>
              <span className="mono">{n}</span>
            </div>
          ))
        ) : (
          <div className="empty">{T("暂无数据", "No data")}</div>
        )}
      </div>
    </>
  );
}

function Resources({ items }: { items: ResourceItem[] }) {
  const T = useT();
  const max = Math.max(1, ...items.map((x) => x.bytes));
  if (!items.length) return <div className="empty">{T("正在读取", "Loading")}</div>;
  return (
    <>
      {items.map((x, i) => (
        <div className="resource-row" key={i}>
          <span>{x.label}</span>
          <span className="track">
            <i style={{ width: `${pct(x.bytes, max)}%` }} />
          </span>
          <span className="mono">{fmtBytes(x.bytes)}</span>
        </div>
      ))}
    </>
  );
}

function PrivacyBoundary() {
  const T = useT();
  return (
    <div className="boundary-grid">
      <article className="boundary-card">
        <div className="boundary-head">
          <span className="source-icon">
            <Icon name="shield" />
          </span>
          <h4>{T("可同步到飞书", "Can sync to Feishu")}</h4>
        </div>
        <p>{T("仅发送生成日报和团队总结所需的整理结果。", "Only structured results needed for reports and team summaries.")}</p>
        <ul>
          <li>{T("工作摘要和关键结论", "Work summaries and key conclusions")}</li>
          <li>{T("提交说明和任务进展", "Commit messages and task progress")}</li>
          <li>{T("来源名称、时间和回链", "Source name, time, and backlink")}</li>
        </ul>
      </article>
      <article className="boundary-card local">
        <div className="boundary-head">
          <span className="source-icon">
            <Icon name="device" />
          </span>
          <h4>{T("仅保存在本地", "Stored locally only")}</h4>
        </div>
        <p>{T("原始内容默认不离开你的电脑。", "Raw content stays on your computer by default.")}</p>
        <ul>
          <li>{T("完整代码和完整 AI 会话", "Full code and AI conversations")}</li>
          <li>{T("密钥、Webhook 和身份凭证", "Secrets, webhooks, and credentials")}</li>
          <li>{T("原始文档、表格和附件", "Original documents, sheets, and attachments")}</li>
        </ul>
      </article>
    </div>
  );
}

function IdentityGroups({ identities, onRemove }: { identities: Identities; onRemove: (value: string) => void }) {
  const T = useT();
  const chips = (values?: string[]) =>
    values && values.length ? (
      values.map((v) => (
        <span className="chip" key={v}>
          {v}{" "}
          <button className="chip-remove" title={T("移除", "Remove")} aria-label={`${T("移除", "Remove")} ${v}`} onClick={() => onRemove(v)}>
            <Icon name="close" />
          </button>
        </span>
      ))
    ) : (
      <span className="identity-empty">{T("尚未添加", "None added")}</span>
    );
  return (
    <div className="identity-groups">
      <div className="identity-group">
        <h4>{T("邮箱", "Email addresses")}</h4>
        <div className="chips">{chips(identities.emails)}</div>
      </div>
      <div className="identity-group">
        <h4>{T("姓名", "Names")}</h4>
        <div className="chips">{chips(identities.names)}</div>
      </div>
    </div>
  );
}

function SourceConfigModal(props: {
  name: string;
  admin: AdminData;
  busy: boolean;
  repoPath: string;
  setRepoPath: (v: string) => void;
  genericPath: string;
  setGenericPath: (v: string) => void;
  fsName: string;
  setFsName: (v: string) => void;
  fsTable: string;
  setFsTable: (v: string) => void;
  fsUrl: string;
  setFsUrl: (v: string) => void;
  onClose: () => void;
  onRepoAdd: () => void;
  onRepoRemove: (path: string) => void;
  onFeishuAdd: () => void;
  onFeishuRemove: (name: string) => void;
  onSourcePathSet: (name: string) => void;
  onOpenSource: (name: string) => void;
}) {
  const T = useT();
  const { name, admin } = props;
  const open = !!name;
  const target = ["git", "feishu"].includes(name) ? name : "generic";
  const titles: Record<string, string> = { git: T("Git 仓库", "Git repositories"), feishu: T("飞书多维表格", "Feishu Bitable") };
  const descs: Record<string, string> = {
    git: T("添加需要采集的仓库。暂停 Git 不会移除已有记录。", "Add repositories to collect. Pausing Git keeps existing records."),
    feishu: T("添加需要采集的多维表格。", "Add Bitables to collect."),
  };
  const env = admin.config.env_keys || {};
  const credentialReady = env.FEISHU_APP_ID && env.FEISHU_APP_SECRET;

  return (
    <div id="source-config" className={`modal${open ? " on" : ""}`} role="dialog" aria-modal="true" aria-hidden={open ? "false" : "true"} aria-labelledby="source-config-title">
      <div className="modal-backdrop" onClick={props.onClose} />
      <div className="modal-panel">
        <div className="modal-head">
          <div className="modal-title">
            <span className="source-icon" id="source-config-icon">
              <Icon name={sourceIconName(name || "git")} />
            </span>
            <div>
              <h2 id="source-config-title">{titles[name] || sourceLabel(T, name)}</h2>
              <p id="source-config-desc">{descs[name] || T("设置这个来源的采集位置。", "Configure where this source is collected from.")}</p>
            </div>
          </div>
          <button className="icon-btn modal-close" onClick={props.onClose} title={T("关闭", "Close")} aria-label={T("关闭", "Close")}>
            <Icon name="close" />
          </button>
        </div>
        <div className="modal-body">
          {/* git */}
          <div className={`config-pane${target === "git" ? " on" : ""}`} data-config-source="git">
            <section className="config-section">
              <div className="config-section-title">{T("添加仓库", "Add repository")}</div>
              <div className="config-add-row">
                <label className="field" htmlFor="repo-path">
                  <span>{T("仓库路径", "Repository path")}</span>
                  <input className="path" id="repo-path" autoComplete="off" spellCheck={false} placeholder="~/Projects/my-project" value={props.repoPath} onChange={(e) => props.setRepoPath(e.target.value)} />
                </label>
                <div className="inline-actions">
                  <button className="act primary" onClick={props.onRepoAdd} disabled={props.busy}>
                    {T("添加仓库", "Add")}
                  </button>
                </div>
              </div>
            </section>
            <section className="config-section">
              <div className="config-section-title">{T("已配置仓库", "Configured repositories")}</div>
              <div id="admin-repos" className="config-list">
                {admin.repos.length ? (
                  admin.repos.map((r) => (
                    <div className="config-item" key={r.path}>
                      <div className="config-item-main">
                        <strong>{r.path.split("/").filter(Boolean).pop() || r.path}</strong>
                        <code>{r.path}</code>
                        <small>
                          {r.git ? r.branch || "Git" : T("路径无效", "Invalid path")}
                          {r.dirty_count ? ` · ${r.dirty_count}${T(" 个未提交更改", " uncommitted changes")}` : ""}
                        </small>
                      </div>
                      <button className="icon-btn danger" onClick={() => props.onRepoRemove(r.path)} title={T("移除仓库", "Remove repository")} aria-label={T("移除仓库", "Remove repository")}>
                        <Icon name="trash" />
                      </button>
                    </div>
                  ))
                ) : (
                  <div className="empty">{T("还没有添加仓库", "No repositories added")}</div>
                )}
              </div>
            </section>
          </div>

          {/* feishu */}
          <div className={`config-pane${target === "feishu" ? " on" : ""}`} data-config-source="feishu">
            <section className="config-section">
              <div id="feishu-credential">
                <div className="credential-note">
                  <i className={`status-dot ${credentialReady ? "" : "warn"}`} />
                  <span>{credentialReady ? T("飞书应用凭证已配置。", "Feishu app credentials are configured.") : T("缺少飞书应用凭证,请先完成应用配置。", "Feishu app credentials are missing.")}</span>
                </div>
              </div>
            </section>
            <section className="config-section">
              <div className="config-section-title">{T("添加多维表格", "Add Bitable")}</div>
              <div className="config-form-grid">
                <label className="field" htmlFor="fs-name">
                  <span>{T("名称", "Name")}</span>
                  <input id="fs-name" autoComplete="off" spellCheck={false} placeholder={T("需求池", "Requirement pool")} value={props.fsName} onChange={(e) => props.setFsName(e.target.value)} />
                </label>
                <label className="field" htmlFor="fs-table">
                  <span>{T("数据表 ID", "Table ID")}</span>
                  <input id="fs-table" autoComplete="off" spellCheck={false} placeholder="tblxxxxxxxx" value={props.fsTable} onChange={(e) => props.setFsTable(e.target.value)} />
                </label>
                <label className="field wide" htmlFor="fs-url">
                  <span>{T("多维表格链接或 App Token", "Bitable link or App Token")}</span>
                  <input className="path" id="fs-url" autoComplete="off" spellCheck={false} placeholder={T("https://... 或 basxxxxxxxx", "https://... or basxxxxxxxx")} value={props.fsUrl} onChange={(e) => props.setFsUrl(e.target.value)} />
                </label>
                <div className="wide">
                  <button className="act primary" onClick={props.onFeishuAdd} disabled={props.busy}>
                    {T("添加", "Add")}
                  </button>
                </div>
              </div>
            </section>
            <section className="config-section">
              <div className="config-section-title">{T("已配置表格", "Configured Bitables")}</div>
              <div id="admin-feishu" className="config-list">
                {(admin.feishu.bitables || []).length ? (
                  admin.feishu.bitables.map((b) => (
                    <div className="config-item" key={b.name}>
                      <div className="config-item-main">
                        <strong>{b.name}</strong>
                        <code>
                          {b.app_token} · {b.table_id}
                        </code>
                      </div>
                      <button className="icon-btn danger" onClick={() => props.onFeishuRemove(b.name)} title={T("移除表格", "Remove Bitable")} aria-label={T("移除表格", "Remove Bitable")}>
                        <Icon name="trash" />
                      </button>
                    </div>
                  ))
                ) : (
                  <div className="empty">{T("还没有添加多维表格", "No Bitables added")}</div>
                )}
              </div>
            </section>
          </div>

          {/* generic */}
          <div className={`config-pane${target === "generic" ? " on" : ""}`} data-config-source="generic">
            <div id="generic-source-body">
              {open && target === "generic" && (
                <GenericSourceConfig
                  name={name}
                  admin={admin}
                  busy={props.busy}
                  genericPath={props.genericPath}
                  setGenericPath={props.setGenericPath}
                  onSourcePathSet={props.onSourcePathSet}
                  onOpenSource={props.onOpenSource}
                />
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function GenericSourceConfig({
  name,
  admin,
  busy,
  genericPath,
  setGenericPath,
  onSourcePathSet,
  onOpenSource,
}: {
  name: string;
  admin: AdminData;
  busy: boolean;
  genericPath: string;
  setGenericPath: (v: string) => void;
  onSourcePathSet: (name: string) => void;
  onOpenSource: (name: string) => void;
}) {
  const T = useT();
  const s = admin.sources.find((x) => x.name === name) || ({ name, enabled: false, checks: [], message: "" } as Source);
  const path = (s.checks?.[0]?.value as string) || "";
  if (s.available === false) {
    return (
      <section className="config-section">
        <div className="config-section-title">{T("当前版本暂不支持采集", "Collection is not available yet")}</div>
        <div className="config-section-copy">{s.message}</div>
        <div className="credential-note">
          <i className="status-dot off" />
          <span>{T("这个来源不会参与同步,也不会计入可用来源。", "This source is excluded from sync and available-source counts.")}</span>
        </div>
      </section>
    );
  }
  if (name === "docs") {
    return (
      <section className="config-section">
        <div className="config-section-title">{T("仓库范围", "Repository scope")}</div>
        <div className="config-section-copy">{T("项目文档从已配置的 Git 仓库中读取 Markdown 文件。", "Project documents read Markdown files from configured Git repositories.")}</div>
        <div className="credential-note">
          <i className={`status-dot ${s.status === "ok" ? "" : "warn"}`} />
          <span>{s.message}</span>
        </div>
        <div className="inline-actions">
          <button className="act primary" onClick={() => onOpenSource("git")}>
            <Icon name="settings" />
            {T("配置 Git 仓库", "Configure Git repositories")}
          </button>
        </div>
      </section>
    );
  }
  if (name === "notes") {
    return (
      <section className="config-section">
        <div className="config-section-title">{T("Loom 笔记库", "Loom notes library")}</div>
        <div className="config-section-copy">
          {T(
            "个人笔记使用 Loom vault 内置目录,通过 loom doc add 或 Loom 命令添加;这里不接受任意来源目录。",
            "Personal notes use the built-in Loom vault. Add material via loom doc add; arbitrary source folders are not configured here.",
          )}
        </div>
        <div className="credential-note">
          <i className={`status-dot ${s.status === "ok" ? "" : "warn"}`} />
          <span>{s.message || path}</span>
        </div>
      </section>
    );
  }
  const labels: Record<string, string> = {
    claude: T("Claude 项目目录", "Claude projects directory"),
    codex: T("Codex 主目录", "Codex home directory"),
    cursor: T("Cursor 数据目录", "Cursor data directory"),
    codebuddy: T("CodeBuddy 数据目录", "CodeBuddy data directory"),
  };
  return (
    <>
      <section className="config-section">
        <div className="config-section-title">{labels[name] || T("扫描目录", "Scan directory")}</div>
        <div className="config-section-copy">{T("Loom 会从这个本地目录读取记录。", "Loom reads records from this local directory.")}</div>
        <div className="config-add-row">
          <label className="field" htmlFor="generic-source-path">
            <span>{T("目录路径", "Directory path")}</span>
            <input className="path" id="generic-source-path" autoComplete="off" spellCheck={false} value={genericPath} onChange={(e) => setGenericPath(e.target.value)} />
          </label>
          <div className="inline-actions">
            <button className="act primary" onClick={() => onSourcePathSet(name)} disabled={busy}>
              {T("保存", "Save")}
            </button>
          </div>
        </div>
      </section>
      <section className="config-section">
        <div className="credential-note">
          <i className={`status-dot ${s.status === "ok" ? "" : "warn"}`} />
          <span>{s.message}</span>
        </div>
      </section>
    </>
  );
}
