// App-shell router — mirrors browse.html's ROUTES / showView / hash routing.
// Keeps the active AppView in top-level state, syncs it to location.hash so
// back/forward + deep-links work, and gates desktop-only views (assistant,
// report) exactly like browse.html does on the web surface.

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { APP_DESKTOP_ONLY_VIEWS, type AppView } from "@/types/loom";

// hash → canonical view (search is an alias of ledger; days of calendar).
const ROUTES: Record<string, AppView> = {
  home: "home",
  ledger: "ledger",
  search: "ledger",
  topics: "topics",
  calendar: "calendar",
  days: "calendar",
  report: "report",
  admin: "admin",
};

export const VIEW_TITLES: Record<AppView, [string, string]> = {
  home: ["首页", "Home"],
  ledger: ["台账", "Ledger"],
  topics: ["主题", "Topics"],
  calendar: ["日历", "Calendar"],
  report: ["日报", "Daily report"],
  admin: ["设置", "Settings"],
};

function isDesktop(): boolean {
  return document.documentElement.dataset.surface === "desktop";
}

// Non-desktop surfaces cannot reach the intelligence views.
function gate(view: AppView): AppView {
  if (!isDesktop() && APP_DESKTOP_ONLY_VIEWS.includes(view)) return "home";
  return view;
}

function viewFromHash(): AppView {
  const hash = (location.hash || "#home").slice(1);
  return gate(ROUTES[hash] || "home");
}

function setDocumentTitle(view: AppView): void {
  document.title = `loom · ${VIEW_TITLES[view][0]}`;
}

type AppRouterValue = {
  view: AppView;
  setView: (view: AppView, pushUrl?: boolean) => void;
};

const AppRouterContext = createContext<AppRouterValue | null>(null);

export function AppRouterProvider({ children }: { children: ReactNode }) {
  const [view, setViewState] = useState<AppView>(() => viewFromHash());

  const setView = useCallback((next: AppView, pushUrl = true) => {
    const target = gate(next);
    setViewState(target);
    setDocumentTitle(target);
    if (pushUrl && location.hash !== "#" + target) {
      history.pushState(null, "", "#" + target);
    }
  }, []);

  // Keep the title correct on first paint + follow browser back/forward.
  useEffect(() => {
    setDocumentTitle(view);
    const onPop = () => {
      const next = viewFromHash();
      setViewState(next);
      setDocumentTitle(next);
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <AppRouterContext.Provider value={{ view, setView }}>{children}</AppRouterContext.Provider>
  );
}

export function useAppRouter(): AppRouterValue {
  const value = useContext(AppRouterContext);
  if (!value) throw new Error("useAppRouter must be used within AppRouterProvider");
  return value;
}
