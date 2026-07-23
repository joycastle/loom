// Faithful React port of browse.html's Calendar view.
//
// Three parts, mirroring browse.html:
//   1. Year activity heatmap  (renderYearMap ~line 1014)  — teal `.ym-cell` scale
//   2. Month calendar grid    (renderCal ~line 1050)      — gold `.cell` scale
//   3. Selected day's records (loadDay / groups)          — grouped by kind
//
// DOM structure + class names replicate browse.html so the ported browse.css
// styles it identically. Data comes from ledger.days() / ledger.day(date).
import { useEffect, useMemo, useState } from "react";
import { useLoom } from "@/runtime/LoomProvider";
import { RecordCard, kindLabel } from "@/components/RecordDrawer";
import { useLang, useT, type Lang, type Translate } from "@/lib/lang";
import type { LoomDayResponse } from "@/types/loom";

// Emoji per kind — matches browse.html's `KIND` map (line 780).
const KIND_EMOJI: Record<string, string> = {
  session: "💬",
  commit: "💻",
  doc: "📄",
  note: "📎",
  report: "📋",
  requirement: "📥",
};

// browse.html group ordering (groups(), line 787).
const GROUP_ORDER = ["report", "session", "commit", "doc", "note", "requirement"];

// month grid header (Mon..Sun), per language.
const weekdays = (lang: Lang): string[] =>
  lang === "zh"
    ? "一二三四五六日".split("")
    : ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
// Year-map weekday labels: only Mon/Wed/Fri shown (browse.html renderYearMap).
const yearDayLabels = (lang: Lang): string[] =>
  lang === "zh" ? ["", "一", "", "三", "", "五", ""] : ["", "Mon", "", "Wed", "", "Fri", ""];
const monthNames = (lang: Lang): string[] =>
  lang === "zh"
    ? ["1月", "2月", "3月", "4月", "5月", "6月", "7月", "8月", "9月", "10月", "11月", "12月"]
    : ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

// Local-timezone ISO date (yyyy-mm-dd) — matches browse.html ymISO().
function ymISO(d: Date): string {
  const o = d.getTimezoneOffset() * 60000;
  return new Date(d.getTime() - o).toISOString().slice(0, 10);
}

// Year heatmap intensity bucket (lvl in renderYearMap).
function yearLevel(c: number): number {
  if (c <= 0) return 0;
  if (c >= 10) return 4;
  if (c >= 6) return 3;
  if (c >= 3) return 2;
  return 1;
}

// Month grid intensity class (heat in renderCal).
function monthHeat(c: number): string {
  if (c >= 10) return "h3";
  if (c >= 4) return "h2";
  if (c >= 1) return "h1";
  return "";
}

type YearCell = {
  ds: string;
  cls: string;
  hidden: boolean;
  title: string;
  count: number;
};

type YearMap = {
  columns: YearCell[][];
  monthRow: string[];
  active: number;
  total: number;
};

// Replicates renderYearMap(): weeks as columns × 7 weekday rows, aligned to
// Monday, spanning ~53 weeks up to today.
function buildYearMap(cnt: Record<string, number>, t: Translate, lang: Lang): YearMap {
  const MONTHS = monthNames(lang);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const start = new Date(today);
  start.setDate(start.getDate() - 370); // ~53 weeks
  start.setDate(start.getDate() - ((start.getDay() + 6) % 7)); // align to Monday

  const columns: YearCell[][] = [];
  const monthRow: string[] = [];
  const cur = new Date(start);
  let total = 0;
  let active = 0;
  let lastMonth = -1;

  while (cur <= today) {
    const firstOfCol = new Date(cur);
    const cells: YearCell[] = [];
    for (let r = 0; r < 7; r++) {
      const ds = ymISO(cur);
      const after = cur > today;
      const c = cnt[ds] || 0;
      if (!after && c > 0) {
        total += c;
        active++;
      }
      cells.push({
        ds,
        count: c,
        hidden: after,
        cls: `ym-cell l${yearLevel(c)}${c ? " has" : ""}`,
        title: `${ds}${c ? ` · ${t(`${c} 条`, `${c} records`)}` : ""}`,
      });
      cur.setDate(cur.getDate() + 1);
    }
    columns.push(cells);
    const m = firstOfCol.getMonth();
    if (m !== lastMonth && firstOfCol.getDate() <= 7) {
      monthRow.push(MONTHS[m]);
      lastMonth = m;
    } else {
      monthRow.push("");
    }
  }
  return { columns, monthRow, active, total };
}

export function CalendarView() {
  const t = useT();
  const { lang } = useLang();
  const { ledger } = useLoom();

  const [cnt, setCnt] = useState<Record<string, number>>({});
  const [months, setMonths] = useState<string[]>([]);
  const [idx, setIdx] = useState(0);
  const [sel, setSel] = useState<string | null>(null);

  const [daysLoading, setDaysLoading] = useState(true);
  const [daysError, setDaysError] = useState<string | null>(null);
  const [hasDays, setHasDays] = useState(true);

  const [dayData, setDayData] = useState<LoomDayResponse | null>(null);
  const [dayLoading, setDayLoading] = useState(false);
  const [dayError, setDayError] = useState<string | null>(null);

  // Load the day → count index once (heatmap + month intensities).
  useEffect(() => {
    let alive = true;
    setDaysLoading(true);
    setDaysError(null);
    ledger
      .days()
      .then((r) => {
        if (!alive) return;
        const map: Record<string, number> = {};
        r.days.forEach((d) => {
          map[d.date] = d.count;
        });
        const ms = [...new Set(r.days.map((d) => d.date.slice(0, 7)))].sort();
        setCnt(map);
        setMonths(ms);
        setHasDays(r.days.length > 0);
        if (r.days.length) {
          setIdx(ms.length - 1); // default to newest month
          setSel(r.days[0].date); // /api/days is reverse-sorted → most recent
        }
        setDaysLoading(false);
      })
      .catch((e: unknown) => {
        if (!alive) return;
        setDaysError(e instanceof Error ? e.message : String(e));
        setDaysLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [ledger]);

  // Load records for the selected day.
  useEffect(() => {
    if (!sel) {
      setDayData(null);
      return;
    }
    let alive = true;
    setDayLoading(true);
    setDayError(null);
    ledger
      .day(sel)
      .then((r) => {
        if (alive) {
          setDayData(r);
          setDayLoading(false);
        }
      })
      .catch((e: unknown) => {
        if (!alive) return;
        setDayError(e instanceof Error ? e.message : String(e));
        setDayLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [ledger, sel]);

  const yearMap = useMemo(() => buildYearMap(cnt, t, lang), [cnt, t, lang]);

  // Pick a day: select it, and jump the month grid if it lives elsewhere.
  const loadDay = (date: string) => {
    setSel(date);
    const mi = months.indexOf(date.slice(0, 7));
    if (mi >= 0 && mi !== idx) setIdx(mi);
  };

  const calNav = (d: number) => {
    setIdx((i) => Math.min(Math.max(i + d, 0), months.length - 1));
  };

  // ---- top-level states ---------------------------------------------------
  if (daysLoading) {
    return (
      <div className="cols">
        <div id="cals">
          <div className="cal">
            <div className="empty">{t("加载中…", "Loading…")}</div>
          </div>
        </div>
        <div id="dbody" />
      </div>
    );
  }
  if (daysError) {
    return (
      <div className="cols">
        <div id="cals">
          <div className="cal">
            <div className="empty">{t("加载失败:", "Failed to load: ")}{daysError}</div>
          </div>
        </div>
        <div id="dbody" />
      </div>
    );
  }
  if (!hasDays) {
    // Mirrors browse.html's no-records branch (loadCal, line 1004).
    return (
      <div className="cols">
        <div id="cals">
          <div className="cal">
            <div className="empty">{t("暂无日历记录", "No calendar records yet")}</div>
          </div>
        </div>
        <div id="dbody">
          <div className="empty">{t("完成首次同步后,可以按日期回顾工作。", "After your first sync, you can review work by date.")}</div>
        </div>
      </div>
    );
  }

  const todayISO = ymISO(new Date());
  const month = months[idx];

  return (
    <>
      {/* 1. Year activity heatmap (renderYearMap) */}
      <div id="yearmap">
        <div className="yearmap-head">
          <h2>{t("年度活动", "Yearly activity")}</h2>
          <small>
            {t(
              `近一年 · ${yearMap.active} 天有记录 · 共 ${yearMap.total} 条`,
              `Past year · ${yearMap.active} active days · ${yearMap.total} records`,
            )}
          </small>
        </div>
        <div className="yearmap-scroll">
          <div className="yearmap-body">
            <div className="yearmap-days">
              {yearDayLabels(lang).map((lbl, i) => (
                <span key={i}>{lbl}</span>
              ))}
            </div>
            <div className="yearmap-cols">
              <div className="yearmap-months">
                {yearMap.monthRow.map((m, i) => (
                  <span key={i}>{m}</span>
                ))}
              </div>
              <div className="yearmap-grid">
                {yearMap.columns.map((col, ci) => (
                  <div className="yearmap-col" key={ci}>
                    {col.map((cell, ri) =>
                      cell.hidden ? (
                        <div
                          className="ym-cell"
                          key={ri}
                          style={{ visibility: "hidden" }}
                        />
                      ) : (
                        <div
                          key={ri}
                          className={`${cell.cls}${cell.ds === sel ? " on" : ""}`}
                          data-d={cell.ds}
                          title={cell.title}
                          onClick={cell.count ? () => loadDay(cell.ds) : undefined}
                        />
                      ),
                    )}
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
        <div className="yearmap-legend">
          {t("少", "Less")} <i className="ym-cell" />
          <i className="ym-cell l1" />
          <i className="ym-cell l2" />
          <i className="ym-cell l3" />
          <i className="ym-cell l4" /> {t("多", "More")}
        </div>
      </div>

      <div className="cols">
        {/* 2. Month calendar grid (renderCal) */}
        <div id="cals">
          <MonthGrid
            month={month}
            cnt={cnt}
            sel={sel}
            todayISO={todayISO}
            atFirst={idx === 0}
            atLast={idx === months.length - 1}
            onNav={calNav}
            onPick={loadDay}
          />
        </div>

        {/* 3. Selected day's records (loadDay + groups) */}
        <div id="dbody">
          <DayPanel
            date={sel}
            loading={dayLoading}
            error={dayError}
            data={dayData}
          />
        </div>
      </div>
    </>
  );
}

function MonthGrid({
  month,
  cnt,
  sel,
  todayISO,
  atFirst,
  atLast,
  onNav,
  onPick,
}: {
  month: string;
  cnt: Record<string, number>;
  sel: string | null;
  todayISO: string;
  atFirst: boolean;
  atLast: boolean;
  onNav: (d: number) => void;
  onPick: (date: string) => void;
}) {
  const t = useT();
  const { lang } = useLang();
  if (!month) return null;
  const [y, mo] = month.split("-").map(Number);
  const dow = (new Date(y, mo - 1, 1).getDay() + 6) % 7; // leading blanks (Mon=0)
  const dim = new Date(y, mo, 0).getDate(); // days in month

  const mTotal = Object.keys(cnt)
    .filter((d) => d.startsWith(month))
    .reduce((a, d) => a + cnt[d], 0);

  const cells = [];
  for (let i = 0; i < dow; i++) {
    cells.push(<div className="cell" key={`blank-${i}`} />);
  }
  for (let d = 1; d <= dim; d++) {
    const ds = `${month}-${String(d).padStart(2, "0")}`;
    const c = cnt[ds] || 0;
    const cls = `cell${c ? ` has ${monthHeat(c)}` : ""}${ds === sel ? " on" : ""}`;
    cells.push(
      <div
        key={ds}
        className={cls}
        data-d={ds}
        title={`${ds}${c ? ` · ${t(`${c} 条`, `${c} records`)}` : ""}`}
        onClick={c ? () => onPick(ds) : undefined}
        style={ds === todayISO ? { boxShadow: "inset 0 0 0 1px var(--cool)" } : undefined}
      >
        {d}
      </div>,
    );
  }

  return (
    <div className="cal">
      <div className="mh">
        <button onClick={() => onNav(-1)} disabled={atFirst}>
          ‹
        </button>
        <span>
          {t(`${y} 年 ${mo} 月`, `${monthNames("en")[mo - 1]} ${y}`)}{" "}
          <small style={{ color: "var(--dim)", fontWeight: 400 }}>{t(`${mTotal} 条`, `${mTotal} records`)}</small>
        </span>
        <button onClick={() => onNav(1)} disabled={atLast}>
          ›
        </button>
      </div>
      <div className="grid">
        {weekdays(lang).map((w, i) => (
          <div className="wd" key={i}>
            {w}
          </div>
        ))}
        {cells}
      </div>
      <div className="legend" style={{ marginTop: 10 }}>
        {t("少", "Less")} <i className="cell h1" />
        <i className="cell h2" />
        <i className="cell h3" /> {t("多", "More")}
      </div>
    </div>
  );
}

function DayPanel({
  date,
  loading,
  error,
  data,
}: {
  date: string | null;
  loading: boolean;
  error: string | null;
  data: LoomDayResponse | null;
}) {
  const t = useT();
  if (!date) {
    return <div className="empty">{t("← 点日历上有热力的日期", "← Pick a highlighted date on the calendar")}</div>;
  }
  if (loading && !data) {
    return <div className="empty">{t("加载中…", "Loading…")}</div>;
  }
  if (error) {
    return <div className="empty">{t("加载失败:", "Failed to load: ")}{error}</div>;
  }
  if (!data) return null;

  const g = data.groups || {};
  const keys = [...new Set([...GROUP_ORDER.filter((k) => g[k]), ...Object.keys(g)])];

  return (
    <>
      <div className="gh" style={{ fontSize: 15, marginTop: 0 }}>
        📅 {data.date} · {t(`${data.total} 条`, `${data.total} records`)}
      </div>
      {keys.length ? (
        keys.map((k) => (
          <div key={k}>
            <div className="gh">
              {KIND_EMOJI[k] || ""} {kindLabel(t, k)} ({g[k].length})
            </div>
            {g[k].map((card) => (
              <RecordCard key={card.id} card={card} />
            ))}
          </div>
        ))
      ) : (
        <div className="empty">{t("空", "Empty")}</div>
      )}
    </>
  );
}
