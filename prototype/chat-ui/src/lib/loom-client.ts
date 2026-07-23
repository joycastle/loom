// Loom admin client — talks to `loom serve` (serve.py). Data reads are plain
// GET endpoints; every write goes through POST /api/admin/action. All requests
// are same-origin and carry the admin token (X-Loom-Token) captured from the
// ?token= boot param; serve.py gates writes on loopback + same-origin + token.
//
// This is the admin console only: there are no chat / agent / personal-AI /
// Feishu-login methods here (those lived in the removed chat runtime).

import { mockClient } from "@/lib/mock-client";
import type {
  LoomAdminActionResponse,
  LoomAdminOverview,
  LoomClientMode,
  LoomDayResponse,
  LoomDaysResponse,
  LoomEntryDetail,
  LoomHome,
  LoomTopicRelationGraph,
  LoomReportMaterialResponse,
  LoomSearchParams,
  LoomSearchResponse,
  LoomSkillActionResponse,
  LoomSkillAgentKey,
  LoomSkillStatusResponse,
  LoomStats,
  LoomTopicResponse,
  LoomTopicsResponse,
} from "@/types/loom";

function buildQuery(params: Record<string, string | number | undefined>): string {
  const q = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === "" || value === null) continue;
    q.set(key, String(value));
  }
  const s = q.toString();
  return s ? `?${s}` : "";
}

type LoomClientOptions = {
  mode: LoomClientMode;
  baseUrl?: string;
  adminToken?: string;
};

async function api<T>(
  baseUrl: string,
  adminToken: string,
  path: string,
  init?: RequestInit,
): Promise<T> {
  const headers = new Headers(init?.headers);
  headers.set("Accept", "application/json");
  if (init?.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  // Same-origin + X-Loom-Token header (mirrors browse.html). The token comes
  // from the ?token= boot param, stored in sessionStorage by lib/boot.ts.
  const token = adminToken || sessionStorage.getItem("loom_admin_token") || "";
  if (token) headers.set("X-Loom-Token", token);
  const response = await fetch(`${baseUrl}${path}`, { ...init, headers });
  const data = (await response.json()) as T & { message?: string; error?: string };
  if (!response.ok) {
    throw new Error(data.message || data.error || `HTTP ${response.status}`);
  }
  return data;
}

export function createLoomClient(options: LoomClientOptions) {
  const baseUrl = (options.baseUrl ?? "").replace(/\/$/, "");
  const token = options.adminToken ?? "";

  if (options.mode === "mock") {
    return mockClient;
  }

  return {
    // ---- ledger browse reads (serve.py GET endpoints) ----
    async stats(): Promise<LoomStats> {
      return api<LoomStats>(baseUrl, token, "/api/stats");
    },

    async search(params: LoomSearchParams): Promise<LoomSearchResponse> {
      return api<LoomSearchResponse>(baseUrl, token, `/api/search${buildQuery({ ...params })}`);
    },

    async days(): Promise<LoomDaysResponse> {
      return api<LoomDaysResponse>(baseUrl, token, "/api/days");
    },

    async day(date: string): Promise<LoomDayResponse> {
      return api<LoomDayResponse>(baseUrl, token, `/api/day${buildQuery({ date })}`);
    },

    async topics(): Promise<LoomTopicsResponse> {
      return api<LoomTopicsResponse>(baseUrl, token, "/api/topics");
    },

    async topic(name: string): Promise<LoomTopicResponse> {
      return api<LoomTopicResponse>(baseUrl, token, `/api/topic${buildQuery({ name })}`);
    },

    async entry(id: string): Promise<LoomEntryDetail> {
      return api<LoomEntryDetail>(baseUrl, token, `/api/entry${buildQuery({ id })}`);
    },

    async topicRelations(): Promise<LoomTopicRelationGraph> {
      return api<LoomTopicRelationGraph>(baseUrl, token, "/api/topic-relations");
    },

    async home(): Promise<LoomHome> {
      return api<LoomHome>(baseUrl, token, "/api/home");
    },

    // ---- admin console (token + loopback + same-origin gated by serve.py) ----
    async adminOverview(): Promise<LoomAdminOverview> {
      return api<LoomAdminOverview>(baseUrl, token, "/api/console/v1/overview");
    },

    async adminAction(payload: Record<string, unknown>): Promise<LoomAdminActionResponse> {
      return api<LoomAdminActionResponse>(baseUrl, token, "/api/admin/action", {
        method: "POST",
        body: JSON.stringify(payload),
      });
    },

    // ---- loom-skill hot-plug into AI agents ----
    async skillsStatus(): Promise<LoomSkillStatusResponse> {
      return api<LoomSkillStatusResponse>(baseUrl, token, "/api/admin/skills");
    },

    async installSkill(agent: LoomSkillAgentKey | "all"): Promise<LoomSkillActionResponse> {
      return api<LoomSkillActionResponse>(baseUrl, token, "/api/admin/action", {
        method: "POST",
        body: JSON.stringify({ action: "skill_install", agent }),
      });
    },

    async uninstallSkill(agent: LoomSkillAgentKey | "all"): Promise<LoomSkillActionResponse> {
      return api<LoomSkillActionResponse>(baseUrl, token, "/api/admin/action", {
        method: "POST",
        body: JSON.stringify({ action: "skill_uninstall", agent }),
      });
    },

    // ---- daily-report material export (no AI generation; hand off externally) ----
    async reportMaterial(date: string): Promise<LoomReportMaterialResponse> {
      return api<LoomReportMaterialResponse>(baseUrl, token, "/api/admin/action", {
        method: "POST",
        body: JSON.stringify({ action: "report_material", date }),
      });
    },

    // ---- UI preferences (theme / language) persisted into config.ui ----
    async savePref(lang: string, theme: string): Promise<LoomAdminActionResponse> {
      return api<LoomAdminActionResponse>(baseUrl, token, "/api/admin/action", {
        method: "POST",
        body: JSON.stringify({ action: "pref_set", lang, theme }),
      });
    },
  };
}

export type LoomClient = ReturnType<typeof createLoomClient>;
