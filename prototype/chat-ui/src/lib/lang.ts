// Bilingual (中文 / English) language system — mirrors browse.html's boot lang
// detection (line 9) and its T() translator + applyLang semantics (~line 731).
//
// browse.html rule:
//   desktop surface → ?lang from the sidecar URL, else "system"
//   web             → localStorage.loom_lang, else "system"
//   "system"        → navigator.language starts with "zh" ? zh : en (default zh)
//
// Unlike browse.html (which reloads on change), the React app switches live by
// driving context state; callers pass both sides inline via t(zh, en), so there
// is no key catalog — exactly like browse.html's data-t="中文|English".
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

export type Lang = "zh" | "en";
export type LangPref = "system" | "zh" | "en";

function isDesktop(): boolean {
  return (
    typeof document !== "undefined" &&
    document.documentElement.dataset.surface === "desktop"
  );
}

// "system" resolution — browse.html's SYSTEM_LANG rule (default zh if unclear).
export function systemLang(): Lang {
  const nav =
    typeof navigator !== "undefined" ? navigator.language || "zh" : "zh";
  return nav.toLowerCase().startsWith("zh") ? "zh" : "en";
}

// The stored preference (may be "system").
export function readLangPref(): LangPref {
  if (typeof document === "undefined") return "system";
  const params = new URLSearchParams(location.search);
  const raw = isDesktop()
    ? params.get("lang") || "system"
    : localStorage.getItem("loom_lang") || "system";
  return raw === "zh" || raw === "en" ? raw : "system";
}

export function resolveLang(pref: LangPref): Lang {
  return pref === "system" ? systemLang() : pref;
}

// Keep <html lang> in sync so the browser + a11y tools know the page language.
export function applyLangAttr(lang: Lang): void {
  if (typeof document !== "undefined") {
    document.documentElement.lang = lang === "zh" ? "zh-CN" : "en";
  }
}

// Called once before React renders (from main.tsx) so <html lang> is correct on
// first paint — mirrors browse.html applying the boot language immediately.
export function applyBootLang(): void {
  applyLangAttr(resolveLang(readLangPref()));
}

type LangContextValue = {
  lang: Lang; // resolved active language
  pref: LangPref; // stored preference (may be "system")
  setLang: (pref: LangPref) => void;
};

const LangContext = createContext<LangContextValue | null>(null);

export function LangProvider({ children }: { children: ReactNode }) {
  const [pref, setPref] = useState<LangPref>(() => readLangPref());
  const lang = resolveLang(pref);

  const setLang = useCallback((next: LangPref) => {
    // Web persistence mirrors browse.html; desktop persistence is handled by the
    // sidecar via savePreferences() (see AdminView), so we only touch localStorage
    // on the web surface. Either way we update state to switch the UI live.
    if (!isDesktop()) {
      if (next === "system") localStorage.removeItem("loom_lang");
      else localStorage.setItem("loom_lang", next);
    }
    setPref(next);
  }, []);

  useEffect(() => {
    applyLangAttr(lang);
  }, [lang]);

  const value = useMemo<LangContextValue>(
    () => ({ lang, pref, setLang }),
    [lang, pref, setLang],
  );

  return createElement(LangContext.Provider, { value }, children);
}

export function useLang(): LangContextValue {
  const ctx = useContext(LangContext);
  if (!ctx) throw new Error("useLang must be used within a <LangProvider>");
  return ctx;
}

// Hook-based translator: const t = useT(); t("中文", "English").
export type Translate = (zh: string, en: string) => string;

export function useT(): Translate {
  const { lang } = useLang();
  return useCallback<Translate>((zh, en) => (lang === "en" ? en : zh), [lang]);
}
