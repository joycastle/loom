import { sleep } from "@/lib/id";
import type {
  LoomAdminActionResponse,
  LoomAdminOverview,
  LoomCard,
  LoomDayResponse,
  LoomDaysResponse,
  LoomEntryDetail,
  LoomHome,
  LoomReportMaterialResponse,
  LoomSearchParams,
  LoomSearchResponse,
  LoomSkillActionResponse,
  LoomSkillAgent,
  LoomSkillAgentKey,
  LoomSkillStatusResponse,
  LoomStats,
  LoomTopicResponse,
  LoomTopicsResponse,
} from "@/types/loom";

// ---- fictional ledger sample data (demo universe · never real records) ----

const MOCK_CARDS: LoomCard[] = [
  {
    id: "rec-0001",
    date: "2026-07-14",
    ts: 1_752_460_800,
    project: "orion-warehouse",
    tool: "claude-code",
    kind: "session",
    summary: "重构 Orion 数仓的维度建模,拆出 dim_player 与 dim_channel",
    ref: "transcript:orion/2026-07-14T09-30.jsonl",
    topics: ["数仓建设", "维度建模"],
  },
  {
    id: "rec-0002",
    date: "2026-07-14",
    ts: 1_752_469_200,
    project: "orion-warehouse",
    tool: "git",
    kind: "commit",
    summary: "feat(etl): 新增渠道归因增量任务,回填近 30 天",
    ref: "git:9f3c2ab",
    topics: ["素材归因"],
  },
  {
    id: "rec-0003",
    date: "2026-07-13",
    ts: 1_752_384_000,
    project: "aegis-antifraud",
    tool: "codex",
    kind: "session",
    summary: "反作弊规则引擎接入设备指纹,补齐夜间刷量识别",
    ref: "transcript:aegis/2026-07-13T21-10.jsonl",
    topics: ["反作弊"],
  },
  {
    id: "rec-0004",
    date: "2026-07-12",
    ts: 1_752_297_600,
    project: "orion-warehouse",
    tool: "note",
    kind: "note",
    summary: "结论:素材归因口径统一按「首触点 + 7 日窗口」,已同步投放同学",
    ref: "note:素材归因/口径.md",
    topics: ["素材归因", "数仓建设"],
  },
  {
    id: "rec-0005",
    date: "2026-07-11",
    ts: 1_752_211_200,
    project: "helios-report",
    tool: "cursor",
    kind: "doc",
    summary: "周报模板 v3:自动汇总各项目提交与结论,支持中英双语导出",
    ref: "doc:helios/weekly-template-v3.md",
    topics: ["工具建设"],
  },
];

function cardById(id: string): LoomCard | undefined {
  return MOCK_CARDS.find((c) => c.id === id);
}

function groupByKind(cards: LoomCard[]): Record<string, LoomCard[]> {
  const groups: Record<string, LoomCard[]> = {};
  for (const card of cards) {
    const kind = card.kind || "other";
    (groups[kind] ||= []).push(card);
  }
  return groups;
}

const MOCK_SKILL_AGENTS: LoomSkillAgent[] = [
  { agent: "claude", label: "Claude Code", label_en: "Claude Code", present: true,
    status: "installed", target: "~/.claude/skills/loom/SKILL.md", strategy: "dedicated" },
  { agent: "codex", label: "Codex CLI", label_en: "Codex CLI", present: true,
    status: "not_installed", target: "~/.codex/skills/loom/SKILL.md", strategy: "dedicated" },
  { agent: "cursor", label: "Cursor", label_en: "Cursor", present: true,
    status: "not_installed", target: "~/.cursor/rules/loom.mdc", strategy: "dedicated" },
  { agent: "codebuddy", label: "CodeBuddy", label_en: "CodeBuddy", present: false,
    status: "not_installed", target: "~/.codebuddy/AGENTS.md", strategy: "marker" },
];

export const mockClient = {
  // ---- ledger browse endpoints (fictional demo data) ----
  async stats(): Promise<LoomStats> {
    await sleep(120);
    const tools: Record<string, number> = {};
    for (const c of MOCK_CARDS) {
      const t = c.tool || "other";
      tools[t] = (tools[t] || 0) + 1;
    }
    return {
      entries: MOCK_CARDS.length,
      days: 4,
      topics: 5,
      projects: 3,
      tagged: MOCK_CARDS.filter((c) => (c.topics?.length ?? 0) > 0).length,
      tools,
      recent: MOCK_CARDS,
    };
  },

  async search(params: LoomSearchParams): Promise<LoomSearchResponse> {
    await sleep(160);
    const q = (params.q || "").trim();
    let hits = MOCK_CARDS.filter((c) => {
      if (params.tool && c.tool !== params.tool) return false;
      if (params.project && c.project !== params.project) return false;
      if (!q) return true;
      return (c.summary || "").includes(q);
    });
    const pageSize = params.page_size || params.limit || 20;
    const offset = params.offset || 0;
    const total = hits.length;
    hits = hits.slice(offset, offset + pageSize);
    return {
      hits: hits.map((c) => ({
        ...c,
        snip: q ? (c.summary || "").replace(q, `<mark>${q}</mark>`) : c.summary,
      })),
      total,
      page: Math.floor(offset / pageSize) + 1,
      page_size: pageSize,
      pages: Math.max(1, Math.ceil(total / pageSize)),
    };
  },

  async days(): Promise<LoomDaysResponse> {
    await sleep(100);
    const counts = new Map<string, number>();
    for (const c of MOCK_CARDS) {
      if (!c.date) continue;
      counts.set(c.date, (counts.get(c.date) || 0) + 1);
    }
    return {
      days: [...counts.entries()]
        .map(([date, count]) => ({ date, count }))
        .sort((a, b) => (a.date < b.date ? 1 : -1)),
    };
  },

  async day(date: string): Promise<LoomDayResponse> {
    await sleep(120);
    const cards = MOCK_CARDS.filter((c) => c.date === date);
    return { date, total: cards.length, groups: groupByKind(cards) };
  },

  async topics(): Promise<LoomTopicsResponse> {
    await sleep(120);
    return {
      tree: [
        { name: "数仓建设", children: [{ name: "维度建模" }, { name: "素材归因" }] },
        { name: "反作弊" },
        { name: "工具建设" },
      ],
      nodes: 5,
      edges: 2,
      loose: [],
      total_tagged: MOCK_CARDS.filter((c) => (c.topics?.length ?? 0) > 0).length,
    };
  },

  async topic(name: string): Promise<LoomTopicResponse> {
    await sleep(120);
    const cards = MOCK_CARDS.filter((c) => c.topics?.includes(name));
    return { name, parents: [], total: cards.length, groups: groupByKind(cards) };
  },

  async entry(id: string): Promise<LoomEntryDetail> {
    await sleep(120);
    const card = cardById(id);
    if (!card) return { id, error: "not found" } as LoomEntryDetail;
    return {
      ...card,
      detail: {
        digest: card.summary,
        body:
          "这是 mock 模式下的示例记录正文。真实模式会展示该条目的完整内容、" +
          "思考过程、计划或提交 diff 等字段。",
        opening: "示例开场:今天围绕 " + (card.project || "项目") + " 展开工作。",
      },
    };
  },

  async home(): Promise<LoomHome> {
    await sleep(120);
    const today = "2026-07-14";
    const todayCards = MOCK_CARDS.filter((c) => c.date === today);
    const sourceCounts: Record<string, number> = {};
    for (const c of todayCards) {
      const t = c.tool || "other";
      sourceCounts[t] = (sourceCounts[t] || 0) + 1;
    }
    return {
      today,
      today_entries: todayCards.length,
      total_entries: MOCK_CARDS.length,
      summarized: todayCards.length,
      classified: todayCards.filter((c) => (c.topics?.length ?? 0) > 0).length,
      source_counts: sourceCounts,
      active_sources: Object.keys(sourceCounts).length,
      available_sources: 5,
      recent: MOCK_CARDS.slice(0, 6),
    };
  },

  // ---- admin console ----
  async adminOverview(): Promise<LoomAdminOverview> {
    await sleep(140);
    const tools: Record<string, number> = {};
    for (const c of MOCK_CARDS) {
      const t = c.tool || "other";
      tools[t] = (tools[t] || 0) + 1;
    }
    return {
      today_entries: 2,
      active_sources: 3,
      available_sources: 5,
      summarized: 2,
      classified: 2,
      local_bytes: 4_812_345,
      recent: MOCK_CARDS.slice(0, 5),
      resources: {
        items: [
          { label: "结构化记录", bytes: 1_240_000 },
          { label: "检索索引", bytes: 2_100_000 },
          { label: "日记与知识文档", bytes: 1_472_345 },
        ],
      },
      admin: {
        sources: [
          { name: "git", enabled: true, available: true, status: "ok", message: "3 个仓库 · 采集 Git 提交与项目文档", category: "development", checks: [] },
          { name: "claude", enabled: true, available: true, status: "ok", message: "~/.claude/projects", category: "development", checks: [{ value: "~/.claude/projects" }] },
          { name: "codex", enabled: true, available: true, status: "ok", message: "~/.codex", category: "development", checks: [{ value: "~/.codex" }] },
          { name: "feishu", enabled: false, available: true, status: "off", message: "未启用", category: "collaboration", checks: [] },
          { name: "notes", enabled: true, available: true, status: "ok", message: "vault/notes", category: "knowledge", checks: [{ value: "~/.loom/vault/notes" }] },
        ],
        broken: [],
        vault: {
          dir: "~/.loom/vault",
          git: true,
          git_remotes: [],
          remote_config: "",
          tracked_risky: [],
          gitignore: { missing: [] },
          dirty: false,
          dirty_count: 0,
        },
        repos: [
          { path: "~/Projects/orion-warehouse", git: true, branch: "main", dirty_count: 0 },
        ],
        identities: { emails: ["you@example.com"], names: ["You"] },
        config: { owner: { name: "You", feishu_name: "" }, env_keys: {} },
        feishu: { bitables: [] },
        collected: {
          entries: MOCK_CARDS.length,
          date_start: "2026-07-11",
          date_end: "2026-07-14",
          index_ready: true,
          tools,
        },
      },
    } as unknown as LoomAdminOverview;
  },

  async adminAction(payload: Record<string, unknown>): Promise<LoomAdminActionResponse> {
    await sleep(200);
    if (payload.action === "sync") {
      return {
        ok: true,
        status: "success",
        message: "同步完成(mock)",
        refresh: true,
        sync: { status: "success", sources: [{ name: "git", status: "success", count: 2 }] },
      } as LoomAdminActionResponse;
    }
    return { ok: true, message: "操作已完成(mock)" };
  },

  // ---- loom-skill hot-plug into AI agents ----
  async skillsStatus(): Promise<LoomSkillStatusResponse> {
    await sleep(80);
    return { ok: true, agents: MOCK_SKILL_AGENTS };
  },

  async installSkill(agent: LoomSkillAgentKey | "all"): Promise<LoomSkillActionResponse> {
    await sleep(120);
    const targets = agent === "all" ? MOCK_SKILL_AGENTS.map((a) => a.agent) : [agent];
    for (const a of MOCK_SKILL_AGENTS) if (targets.includes(a.agent)) a.status = "installed";
    return {
      ok: true,
      results: targets.map((a) => {
        const spec = MOCK_SKILL_AGENTS.find((x) => x.agent === a)!;
        return {
          ok: true, agent: a, label: spec.label, label_en: spec.label_en,
          action: "installed", target: spec.target, strategy: spec.strategy,
          drift: false, backup: null, message: `${spec.label}: installed`,
        };
      }),
      agents: MOCK_SKILL_AGENTS,
    };
  },

  async uninstallSkill(agent: LoomSkillAgentKey | "all"): Promise<LoomSkillActionResponse> {
    await sleep(120);
    const targets = agent === "all" ? MOCK_SKILL_AGENTS.map((a) => a.agent) : [agent];
    for (const a of MOCK_SKILL_AGENTS) if (targets.includes(a.agent)) a.status = "not_installed";
    return {
      ok: true,
      results: targets.map((a) => {
        const spec = MOCK_SKILL_AGENTS.find((x) => x.agent === a)!;
        return {
          ok: true, agent: a, label: spec.label, label_en: spec.label_en,
          action: "uninstalled", target: spec.target, strategy: spec.strategy,
          drift: false, backup: null, message: `${spec.label}: uninstalled`,
        };
      }),
      agents: MOCK_SKILL_AGENTS,
    };
  },

  // ---- daily-report material export ----
  async reportMaterial(date: string): Promise<LoomReportMaterialResponse> {
    await sleep(160);
    return {
      ok: true,
      date,
      material:
        `# ${date} 原材料(供 AI 写日报)\n\n` +
        "## 提交 (1)\n- feat(etl): 新增渠道归因增量任务,回填近 30 天  (4文件 +120/-8)\n\n" +
        "## AI 会话 (1)\n- [claude-code] 重构 Orion 数仓的维度建模\n\n" +
        "---\n请基于以上真实痕迹,以第一人称写这天的日报。",
    };
  },

  // ---- UI preferences ----
  async savePref(_lang: string, _theme: string): Promise<LoomAdminActionResponse> {
    await sleep(40);
    return { ok: true, message: "已保存界面偏好(mock)" };
  },
};
