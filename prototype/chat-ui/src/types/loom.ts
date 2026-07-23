export type LoomClientMode = "mock" | "live";

// ---- app shell views (admin console) ----
// home | ledger | topics | calendar | report | admin.
export type AppView =
  | "home"
  | "ledger"
  | "topics"
  | "calendar"
  | "report"
  | "admin";

// No desktop-only gating: `loom serve` is the web admin console and every view
// is reachable in the browser.
export const APP_DESKTOP_ONLY_VIEWS: AppView[] = [];

// The shared "card" shape returned by every ledger list endpoint.
export type LoomCard = {
  id: string;
  date?: string;
  ts?: number;
  project?: string;
  tool?: string;
  kind?: string;
  summary?: string;
  ref?: string;
  topics?: string[];
};

// Search hits add a (possibly highlight-marked) snippet.
export type LoomSearchHit = LoomCard & { snip?: string };

// An automatically derived structural edge returned with /api/entry. The
// backend includes the target's card fields so the drawer can render and open
// it without another list request.
export type LoomRelatedEntry = LoomCard & {
  score: number;
  reasons: string[];
};

export type LoomRelationGraphNode = LoomCard & { degree: number };
export type LoomRelationGraphEdge = {
  source: string;
  target: string;
  score: number;
  reasons: string[];
};
export type LoomRelationGraph = {
  nodes: LoomRelationGraphNode[];
  edges: LoomRelationGraphEdge[];
  total_entries: number;
  total_nodes: number;
  total_edges: number;
  shown_nodes: number;
  shown_edges: number;
};

export type LoomTopicRelationNode = {
  name: string;
  count: number;
  direct: number;
  multi?: boolean;
  kinds: Record<string, number>;
};
export type LoomTopicRelationEdge = {
  source: string;
  target: string;
  count: number;
  score: number;
  reasons: string[];
};
export type LoomTopicRelationGraph = {
  nodes: LoomTopicRelationNode[];
  hierarchy_edges: [string, string][];
  relation_edges: LoomTopicRelationEdge[];
  total_tagged: number;
  total_relation_edges: number;
  mapped_relation_edges: number;
  within_topic_edges: number;
};

export type LoomStats = {
  entries: number;
  days: number;
  topics: number;
  projects: number;
  tagged: number;
  tools: Record<string, number>;
  recent: LoomCard[];
};

export type LoomSearchParams = {
  q?: string;
  tool?: string;
  project?: string;
  since?: string;
  until?: string;
  limit?: number;
  offset?: number;
  // The real sidecar backend paginates by page/page_size (offset is derived
  // server-side and ignored); the mock client paginates by limit/offset. We
  // send both so either backend returns the requested page.
  page?: number;
  page_size?: number;
};

export type LoomSearchResponse = {
  hits: LoomSearchHit[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
};

export type LoomDayCount = { date: string; count: number };

export type LoomDaysResponse = { days: LoomDayCount[] };

export type LoomDayResponse = {
  date: string;
  total: number;
  groups: Record<string, LoomCard[]>;
};

export type LoomTopicNode = { name: string; count?: number; children?: LoomTopicNode[] };

export type LoomTopicsResponse = {
  tree: LoomTopicNode[];
  nodes?: number;
  edges?: number;
  loose?: string[];
  total_tagged?: number;
};

export type LoomTopicResponse = {
  name: string;
  parents?: string[];
  total: number;
  groups: Record<string, LoomCard[]>;
};

// Full entry = raw record dict + topics + a kind-dependent `detail` bag.
export type LoomEntryDetail = LoomCard & {
  topics?: string[];
  related?: LoomRelatedEntry[];
  detail?: Record<string, unknown>;
  error?: string;
  [key: string]: unknown;
};

// ---- /api/home (dashboard) ----
export type LoomHome = {
  today: string;
  today_entries: number;
  total_entries: number;
  summarized: number;
  classified: number;
  source_counts: Record<string, number>;
  active_sources: number;
  available_sources: number;
  recent: LoomCard[];
};

// ---- loom-skill hot-plug (POST /api/admin/action skill_install|skill_uninstall,
//      GET /api/admin/skills) ----
export type LoomSkillAgentKey = "claude" | "codex" | "cursor" | "codebuddy";

export type LoomSkillStatus =
  | "installed"
  | "update_available"
  | "drifted"
  | "missing"
  | "foreign"
  | "not_installed";

export type LoomSkillAgent = {
  agent: LoomSkillAgentKey;
  label: string;
  label_en: string;
  present: boolean;
  status: LoomSkillStatus;
  target: string;
  strategy: "dedicated" | "marker";
  version?: number | null;
  installed_at?: string | null;
};

export type LoomSkillStatusResponse = {
  ok: boolean;
  agents: LoomSkillAgent[];
  error?: string;
};

export type LoomSkillActionResult = {
  ok: boolean;
  agent: LoomSkillAgentKey;
  label: string;
  label_en: string;
  action: string;
  target: string;
  strategy: "dedicated" | "marker";
  present?: boolean;
  drift?: boolean;
  backup?: string | null;
  message?: string;
};

export type LoomSkillActionResponse = {
  ok: boolean;
  results: LoomSkillActionResult[];
  agents: LoomSkillAgent[];
  error?: string;
  message?: string;
};

// ---- report material export (POST /api/admin/action action=report_material) ----
// Aggregates a day's raw traces for an external AI / Feishu agent to draft the
// report from. Loom itself does not generate the report.
export type LoomReportMaterialResponse = {
  ok: boolean;
  date: string;
  material: string;
  message?: string;
  error?: string;
};

// ---- /api/console/v1/overview (admin overview) ----
export type LoomSource = {
  name: string;
  enabled: boolean;
  available?: boolean;
  status?: string;
  message?: string;
  [key: string]: unknown;
};
export type LoomAdminOverview = {
  sources: LoomSource[];
  stats?: LoomStats;
  tools?: Record<string, number>;
  recent?: LoomCard[];
  [key: string]: unknown;
};

// ---- /api/admin/action (POST) ----
export type LoomAdminActionResponse = {
  ok: boolean;
  message?: string;
  error?: string;
  needs_confirm?: string;
  log?: string;
  [key: string]: unknown;
};
