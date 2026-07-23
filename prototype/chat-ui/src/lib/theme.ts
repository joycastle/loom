// Theme + boot handling — mirrors browse.html's inline boot script (line 9)
// and its DOMContentLoaded theme wiring (paintTheme + #themebtn toggle).
//
// Desktop surface reads ?theme / ?lang from the sidecar URL; web reads
// localStorage. "system" resolves against prefers-color-scheme. The resolved
// value is written to <html data-theme=…> and the <meta name=theme-color>.
//
// The React app keeps a single theme state in <ThemeProvider> (mirrors
// <LangProvider> in lib/lang.ts): every control (top-bar toggle + settings
// select) reads/writes it through useTheme(), so they never drift. Local
// persistence (localStorage on web) lives here; backend persistence
// (savePreferences) is done by the caller that owns the loom client.

import {
  createContext,
  createElement,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

export type ThemePref = "system" | "light" | "dark";
export type Theme = "light" | "dark";

declare global {
  interface Window {
    __LOOM_BOOT__?: { desktop: boolean; theme: ThemePref; language: string };
  }
}

function isDesktop(): boolean {
  return document.documentElement.dataset.surface === "desktop";
}

export function systemTheme(): Theme {
  return matchMedia("(prefers-color-scheme:dark)").matches ? "dark" : "light";
}

// The user's stored preference (may be "system").
export function readThemePref(): ThemePref {
  const params = new URLSearchParams(location.search);
  const raw = isDesktop()
    ? params.get("theme") || "system"
    : localStorage.getItem("loom_theme") || "system";
  return raw === "light" || raw === "dark" ? raw : "system";
}

export function readLanguagePref(): string {
  const params = new URLSearchParams(location.search);
  return isDesktop()
    ? params.get("lang") || "system"
    : localStorage.getItem("loom_lang") || "system";
}

export function resolveTheme(pref: ThemePref): Theme {
  return pref === "system" ? systemTheme() : pref;
}

// theme-color meta mirrors browse.html: light #F3F6F4, dark #0E1117.
function paintThemeColor(theme: Theme): void {
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute("content", theme === "light" ? "#F3F6F4" : "#0E1117");
}

export function applyTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme;
  paintThemeColor(theme);
}

// Called once before React renders (from main.tsx) so there is no theme flash.
export function applyBootTheme(): void {
  const desktop = isDesktop();
  const pref = readThemePref();
  const language = readLanguagePref();
  window.__LOOM_BOOT__ = { desktop, theme: pref, language };
  applyTheme(resolveTheme(pref));
}

export function currentTheme(): Theme {
  return document.documentElement.dataset.theme === "light" ? "light" : "dark";
}

// Local persistence for the theme preference — mirrors lib/lang.ts's setLang:
// only web writes localStorage; on desktop the sidecar owns persistence via
// savePreferences() (called by the control), and ?theme seeds the next boot.
function persistThemePrefLocal(pref: ThemePref): void {
  if (isDesktop()) return;
  if (pref === "system") localStorage.removeItem("loom_theme");
  else localStorage.setItem("loom_theme", pref);
}

// ---------------------------------------------------------------------------
// Shared theme state — one source of truth for every theme control, exactly
// like <LangProvider>/useLang in lib/lang.ts.
// ---------------------------------------------------------------------------
type ThemeContextValue = {
  theme: Theme; // resolved active theme (light/dark)
  pref: ThemePref; // stored preference (may be "system")
  setThemePref: (pref: ThemePref) => void; // apply live + persist locally
};

const ThemeContext = createContext<ThemeContextValue | null>(null);

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [pref, setPref] = useState<ThemePref>(() => readThemePref());
  const theme = resolveTheme(pref);

  const setThemePref = useCallback((next: ThemePref) => {
    persistThemePrefLocal(next);
    setPref(next);
  }, []);

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  const value = useMemo<ThemeContextValue>(
    () => ({ theme, pref, setThemePref }),
    [theme, pref, setThemePref],
  );

  return createElement(ThemeContext.Provider, { value }, children);
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useTheme must be used within a <ThemeProvider>");
  return ctx;
}
