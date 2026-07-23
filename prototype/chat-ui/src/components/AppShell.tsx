// App shell — top bar + nav + view containers for the `loom serve` admin
// console. Structure and class names mirror browse.html so the ported browse.css
// styles it identically (top-tab nav on web, left sidebar on the desktop
// surface). The chat/assistant view has been removed; this is admin-only.

import { type ReactNode } from "react";
import { BrandMark } from "@/components/BrandMark";
import { NavIcon, type IconName } from "@/components/NavIcon";
import { RecordDrawer } from "@/components/RecordDrawer";
import { HomeView } from "@/views/HomeView";
import { LedgerView } from "@/views/LedgerView";
import { TopicsView } from "@/views/TopicsView";
import { CalendarView } from "@/views/CalendarView";
import { ReportView } from "@/views/ReportView";
import { AdminView } from "@/views/AdminView";
import { useAppRouter } from "@/lib/app-router";
import { useTheme, type ThemePref } from "@/lib/theme";
import { useLang, useT } from "@/lib/lang";
import { useLoom } from "@/runtime/LoomProvider";
import type { AppView } from "@/types/loom";

type NavItem = { view: AppView; zh: string; en: string; icon: IconName };

const WORK_ITEMS: NavItem[] = [
  { view: "home", zh: "首页", en: "Home", icon: "home" },
  { view: "ledger", zh: "台账", en: "Ledger", icon: "ledger" },
  { view: "topics", zh: "主题", en: "Topics", icon: "topics" },
  { view: "calendar", zh: "日历", en: "Calendar", icon: "calendar" },
  { view: "report", zh: "日报", en: "Daily report", icon: "report" },
];

function NavButton({ item }: { item: NavItem }) {
  const { view, setView } = useAppRouter();
  const t = useT();
  const active = view === item.view;
  return (
    <button
      type="button"
      data-v={item.view}
      className={active ? "on" : undefined}
      aria-current={active ? "page" : undefined}
      onClick={() => setView(item.view, true)}
    >
      <span className="nav-icon" data-nav-icon={item.icon}>
        <NavIcon name={item.icon} />
      </span>
      <span>{t(item.zh, item.en)}</span>
    </button>
  );
}

function ThemeToggle() {
  const t = useT();
  const { theme, setThemePref } = useTheme();
  const { pref: langPref } = useLang();
  const { ledger } = useLoom();
  const light = theme === "light";
  const onToggle = () => {
    const next: ThemePref = light ? "dark" : "light";
    setThemePref(next); // apply live + localStorage (shared state)
    // Best-effort persist to config.ui so the choice survives a restart.
    void ledger.savePref(langPref, next).catch(() => {});
  };
  return (
    <button
      id="themebtn"
      type="button"
      aria-label={t("切换亮暗主题", "Toggle light/dark theme")}
      title={light ? t("切换到暗色", "Switch to dark") : t("切换到亮色", "Switch to light")}
      onClick={onToggle}
    >
      <NavIcon name={light ? "sun" : "moon"} />
    </button>
  );
}

function LangToggle() {
  const { lang, setLang } = useLang();
  const { pref: themePref } = useTheme();
  const { ledger } = useLoom();
  const t = useT();
  const onToggle = () => {
    const next = lang === "zh" ? "en" : "zh";
    setLang(next); // live switch + localStorage (web)
    void ledger.savePref(next, themePref).catch(() => {});
  };
  return (
    <button
      id="langbtn"
      type="button"
      aria-label={t("切换界面语言", "Toggle interface language")}
      title={lang === "zh" ? t("切换到英文", "Switch to English") : t("切换到中文", "Switch to Chinese")}
      onClick={onToggle}
    >
      {lang === "zh" ? "EN" : "中"}
    </button>
  );
}

const VIEW_CONTENT: Record<AppView, () => ReactNode> = {
  home: () => <HomeView />,
  ledger: () => <LedgerView />,
  topics: () => <TopicsView />,
  calendar: () => <CalendarView />,
  report: () => <ReportView />,
  admin: () => <AdminView />,
};

function ViewPane({ view }: { view: AppView }) {
  const { view: active } = useAppRouter();
  const on = active === view;
  return (
    <section id={`v-${view}`} className={`view${on ? " on" : ""}`}>
      {VIEW_CONTENT[view]()}
    </section>
  );
}

const ALL_VIEWS: AppView[] = ["home", "ledger", "topics", "calendar", "report", "admin"];

export function AppShell() {
  const { setView } = useAppRouter();
  const t = useT();
  return (
    <div className="wrap">
      <a className="skip" href="#main">
        {t("跳到内容", "Skip to content")}
      </a>
      <header data-tauri-drag-region="">
        <div className="brand" data-tauri-drag-region="">
          <BrandMark />
          <div className="brand-copy" data-tauri-drag-region="">
            <span className="nm" translate="no">
              Loom
            </span>
            <span className="brand-subtitle">{t("个人工作台账", "personal work ledger")}</span>
          </div>
        </div>
        <nav aria-label="Primary">
          <div className="nav-group nav-work">
            <span className="nav-section">{t("工作", "WORK")}</span>
            {WORK_ITEMS.map((item) => (
              <NavButton key={item.view} item={item} />
            ))}
          </div>
          <button
            type="button"
            data-v="admin"
            className="web-settings"
            onClick={() => setView("admin", true)}
          >
            <span className="nav-icon" data-nav-icon="settings">
              <NavIcon name="settings" />
            </span>
            <span>{t("设置", "Settings")}</span>
          </button>
          <div className="nav-bottom">
            <div className="nav-bottom-main" data-desktop-only="">
              <button
                className="sidebar-account"
                id="sidebar-account"
                type="button"
                onClick={() => setView("admin", true)}
              >
                <span className="sidebar-avatar">L</span>
                <span className="sidebar-account-copy">
                  <strong>{t("本地台账", "Local ledger")}</strong>
                  <small>{t("loom serve 管理页", "loom serve admin")}</small>
                </span>
                <i className="sidebar-state off" />
              </button>
              <NavButton item={{ view: "admin", zh: "设置", en: "Settings", icon: "settings" }} />
            </div>
            <div className="nav-toggles">
              <LangToggle />
              <ThemeToggle />
            </div>
          </div>
        </nav>
      </header>

      <main id="main">
        {ALL_VIEWS.map((view) => (
          <ViewPane key={view} view={view} />
        ))}
      </main>
      <RecordDrawer />
    </div>
  );
}
