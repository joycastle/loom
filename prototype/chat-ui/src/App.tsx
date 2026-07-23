import { useState } from "react";
import "./browse.css";
import "./polish.css";
import { AppShell } from "@/components/AppShell";
import { AppRouterProvider } from "@/lib/app-router";
import { LoomProvider } from "@/runtime/LoomProvider";
import { hasLoomToken } from "@/lib/boot";
import { LangProvider, useT } from "@/lib/lang";
import { ThemeProvider } from "@/lib/theme";
import type { LoomClientMode } from "@/types/loom";

// Small floating developer toggle (dev builds only) that lets the admin console
// run in the browser against mock data or a live `loom serve` sidecar. Mock is
// the default when there is no admin token in the URL.
function DevDrawer({
  mode,
  setMode,
  baseUrl,
  setBaseUrl,
  adminToken,
  setAdminToken,
  onClose,
}: {
  mode: LoomClientMode;
  setMode: (m: LoomClientMode) => void;
  baseUrl: string;
  setBaseUrl: (v: string) => void;
  adminToken: string;
  setAdminToken: (v: string) => void;
  onClose: () => void;
}) {
  const t = useT();
  return (
    <div className="loom-dev-drawer">
      <label>
        {t("模式", "Mode")}
        <select value={mode} onChange={(e) => setMode(e.target.value as LoomClientMode)}>
          <option value="mock">{t("mock（本地演示）", "mock (local demo)")}</option>
          <option value="live">{t("live（接 loom serve）", "live (loom serve)")}</option>
        </select>
      </label>
      {mode === "live" ? (
        <>
          <label className="loom-dev-grow">
            baseUrl
            <input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} />
          </label>
          <label>
            token
            <input value={adminToken} onChange={(e) => setAdminToken(e.target.value)} />
          </label>
        </>
      ) : null}
      <button type="button" className="loom-btn" onClick={onClose}>
        {t("收起", "Collapse")}
      </button>
    </div>
  );
}

function AppInner() {
  const t = useT();
  // Boot into live mode when the sidecar handed us an admin token; otherwise
  // fall back to the mock demo universe.
  const [mode, setMode] = useState<LoomClientMode>(hasLoomToken() ? "live" : "mock");
  const [baseUrl, setBaseUrl] = useState("");
  const [adminToken, setAdminToken] = useState("");
  const [devOpen, setDevOpen] = useState(false);

  return (
    <>
      {/* Remount the client when the connection identity changes. */}
      <LoomProvider key={`${mode}:${baseUrl}:${adminToken}`} mode={mode} baseUrl={baseUrl} adminToken={adminToken}>
        <AppRouterProvider>
          <AppShell />
        </AppRouterProvider>
      </LoomProvider>
      {/* Dev-only escape hatch (mock/live switch, sidecar URL + token). Gated on
          import.meta.env.DEV so Vite drops it from production builds. */}
      {import.meta.env.DEV ? (
        <>
          <button
            type="button"
            className="loom-dev-fab"
            title={t("开发选项", "Developer options")}
            onClick={() => setDevOpen((v) => !v)}
          >
            ⚙
          </button>
          {devOpen ? (
            <DevDrawer
              mode={mode}
              setMode={setMode}
              baseUrl={baseUrl}
              setBaseUrl={setBaseUrl}
              adminToken={adminToken}
              setAdminToken={setAdminToken}
              onClose={() => setDevOpen(false)}
            />
          ) : null}
        </>
      ) : null}
    </>
  );
}

export default function App() {
  return (
    <LangProvider>
      <ThemeProvider>
        <AppInner />
      </ThemeProvider>
    </LangProvider>
  );
}
