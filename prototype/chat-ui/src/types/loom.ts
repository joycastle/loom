export type LoomCitation = {
  source: string;
  title: string;
  url?: string;
};

export type LoomProposedAction = {
  proposal_id: string;
  action: string;
  target?: string;
  content?: string;
  reason?: string;
  risk: "low" | "medium" | "high";
  status: string;
};

export type LoomUiAction =
  | {
      kind: "agent_proposal";
      proposal_id: string;
      title?: string;
      summary?: string;
      status: string;
      risk?: "low" | "medium" | "high";
      receipt_text?: string;
    }
  | {
      kind: "agent_job";
      job_id: string;
      title?: string;
      status: string;
      progress_text?: string;
    }
  | {
      kind: "open_ledger_search" | "open_source_settings" | "open_sync_center" | "start_sync" | "open_native_picker";
      label?: string;
      label_en?: string;
      query?: string;
    };

export type LoomMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  pending?: boolean;
  // Set client-side when a turn resolves via an error path (network/backend/no
  // reply). Drives per-turn error styling; not a backend field.
  error?: boolean;
  attachments?: { id: string; name: string }[];
  citations?: LoomCitation[];
  proposed_actions?: LoomProposedAction[];
  ui_actions?: LoomUiAction[];
  response_kind?: string;
  action_status?: string;
};

export type LoomSendContext = {
  local: "none" | "today";
  feishu: boolean;
  date: string;
  source_config_ids: string[];
};

export type LoomAssistantPayload = {
  id?: string;
  content?: string;
  citations?: LoomCitation[];
  proposed_actions?: LoomProposedAction[];
  ui_actions?: LoomUiAction[];
  response_kind?: string;
  action_status?: string;
};

export type LoomSendResponse = {
  ok: boolean;
  status?: string;
  message?: string;
  conversation_id?: string;
  job_id?: string;
  poll_after_seconds?: number;
  assistant_message?: LoomAssistantPayload;
};

export type LoomJobResponse = LoomSendResponse & {
  status: string;
};

export type LoomProposalDetail = {
  proposal_id: string;
  status: string;
  summary?: string;
  risk?: "low" | "medium" | "high";
  impact?: string[];
  evidence?: string[];
  receipt?: { message?: string; job_id?: string; job_status?: string; summary?: string };
};

export type LoomClientMode = "mock" | "live";

// ---- ledger / browse views (home · search · journal · topics · record) ----

export type LoomView = "chat" | "home" | "search" | "journal" | "topics";

// ---- app shell views (admin console; chat/assistant removed) ----
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

export type LoomTopicNode = { name: string; children?: LoomTopicNode[] };

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
  detail?: Record<string, unknown>;
  error?: string;
  [key: string]: unknown;
};

// The subset of client methods that browse views need. Both the live client
// and the mock client satisfy this, so it can be handed to views uniformly.
export type LoomLedger = {
  stats: () => Promise<LoomStats>;
  search: (params: LoomSearchParams) => Promise<LoomSearchResponse>;
  days: () => Promise<LoomDaysResponse>;
  day: (date: string) => Promise<LoomDayResponse>;
  topics: () => Promise<LoomTopicsResponse>;
  topic: (name: string) => Promise<LoomTopicResponse>;
  entry: (id: string) => Promise<LoomEntryDetail>;
};

export type LoomConversation = {
  id: string;
  title: string;
  messages: LoomMessage[];
  server_id: string;
  updated_at: number;
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

// ---- /api/enterprise/v1/preferences (POST) ----
export type LoomPreferencesResponse = {
  ok: boolean;
  message?: string;
  error?: string;
};

// ---- /api/enterprise/v1/install-cli (POST) ----
export type LoomInstallCliResponse = {
  ok: boolean;
  path?: string;
  target?: string;
  on_path?: boolean;
  command?: string;
  message?: string;
  error?: string;
};

// ---- /api/enterprise/v1/skills/* (loom-skill hot-plug) ----
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

// ---- /api/enterprise/v1/reports/preview (GET) ----
export type LoomReportPreview = {
  date: string;
  local_entries?: number;
  source_counts?: Record<string, number>;
  upload_policy?: string;
  [key: string]: unknown;
};

// A report draft may come back as a string or a { markdown|content } bag.
export type LoomReportDraft = string | { markdown?: string; content?: string };

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

// ---- /api/enterprise/v1/reports/daily (POST) + report-jobs/{id} (GET) ----
export type LoomReportJobResponse = {
  ok: boolean;
  status?: string;
  message?: string;
  job_id?: string;
  poll_after_seconds?: number;
  draft?: LoomReportDraft;
  [key: string]: unknown;
};

// ---- /api/agent/v1/proposals (list) ----
export type LoomProposalSummary = {
  proposal_id: string;
  status: string;
  summary?: string;
  risk?: "low" | "medium" | "high";
  action?: string;
  [key: string]: unknown;
};
export type LoomProposalsListResponse = {
  proposals: LoomProposalSummary[];
  [key: string]: unknown;
};

// ---- /api/agent/v1/jobs (list) + jobs/{id} (single) ----
export type LoomAgentJob = {
  job_id: string;
  status: string;
  progress?: { message?: string; [key: string]: unknown };
  poll_after_seconds?: number;
  [key: string]: unknown;
};
export type LoomAgentJobsListResponse = {
  jobs: LoomAgentJob[];
  [key: string]: unknown;
};

// ---- /api/agent/v1/source-proposals (POST) ----
export type LoomSourceProposalResponse = {
  proposal?: LoomProposalSummary;
  error?: string;
  message?: string;
  [key: string]: unknown;
};

// ---- /api/agent/v1/onboarding (GET) ----
export type LoomOnboardingStep = {
  id: string;
  title?: string;
  done?: boolean;
  [key: string]: unknown;
};
export type LoomOnboardingState = {
  steps?: LoomOnboardingStep[];
  completed?: number;
  total?: number;
  [key: string]: unknown;
};

// ---- /api/agent/v1/picker (POST) ----
export type LoomPickerResponse = {
  status: string;
  discovery?: { candidates?: { candidate_id: string; display_name?: string }[] };
  [key: string]: unknown;
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

