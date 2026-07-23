// Custom, theme-consistent date picker for the ledger filters. Replaces the
// native <input type="date"> whose popup calendar can't be styled to match the
// app. Pure React + design tokens (styled in polish.css); no external library.
import { useEffect, useMemo, useRef, useState } from "react";
import { Calendar, ChevronLeft, ChevronRight } from "lucide-react";
import { useT } from "@/lib/lang";

// Local-time YYYY-MM-DD (matches how the ledger filters store dates).
function toISO(d: Date): string {
  const x = new Date(d.getTime() - d.getTimezoneOffset() * 60000);
  return x.toISOString().slice(0, 10);
}
function parseISO(s: string): Date | null {
  const [y, m, d] = (s || "").split("-").map(Number);
  return y && m && d ? new Date(y, m - 1, d) : null;
}
function firstOfMonth(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth(), 1);
}

export function DatePicker({
  value,
  onChange,
  placeholder,
  ariaLabel,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  ariaLabel?: string;
}) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const selected = useMemo(() => parseISO(value), [value]);
  const [view, setView] = useState<Date>(() => firstOfMonth(selected || new Date()));
  const rootRef = useRef<HTMLDivElement>(null);

  // Re-center the visible month on the selected date whenever it changes.
  useEffect(() => {
    if (selected) setView(firstOfMonth(selected));
  }, [value]); // eslint-disable-line react-hooks/exhaustive-deps

  // Dismiss on outside click / Escape while open.
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const weekdays = t("日 一 二 三 四 五 六", "S M T W T F S").split(" ");
  const title = t(
    `${view.getFullYear()} 年 ${view.getMonth() + 1} 月`,
    `${view.toLocaleString("en", { month: "long" })} ${view.getFullYear()}`,
  );

  const cells = useMemo(() => {
    const startDow = view.getDay(); // view is the 1st of the month
    const days = new Date(view.getFullYear(), view.getMonth() + 1, 0).getDate();
    const arr: (Date | null)[] = [];
    for (let i = 0; i < startDow; i++) arr.push(null);
    for (let d = 1; d <= days; d++) arr.push(new Date(view.getFullYear(), view.getMonth(), d));
    return arr;
  }, [view]);

  const todayISO = toISO(new Date());
  const shift = (delta: number) =>
    setView(new Date(view.getFullYear(), view.getMonth() + delta, 1));
  const pick = (d: Date) => {
    onChange(toISO(d));
    setOpen(false);
  };

  return (
    <div className="loom-dp" ref={rootRef}>
      <button
        type="button"
        className={`loom-dp-field${value ? " has" : ""}`}
        aria-label={ariaLabel}
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <Calendar size={14} strokeWidth={2} />
        <span className="loom-dp-value">{value || placeholder || t("选择日期", "Pick a date")}</span>
      </button>
      {open ? (
        <div className="loom-dp-pop" role="dialog" aria-label={ariaLabel}>
          <div className="loom-dp-head">
            <button type="button" className="loom-dp-nav" onClick={() => shift(-1)} aria-label={t("上个月", "Previous month")}>
              <ChevronLeft size={16} strokeWidth={2} />
            </button>
            <span className="loom-dp-title">{title}</span>
            <button type="button" className="loom-dp-nav" onClick={() => shift(1)} aria-label={t("下个月", "Next month")}>
              <ChevronRight size={16} strokeWidth={2} />
            </button>
          </div>
          <div className="loom-dp-grid loom-dp-dow">
            {weekdays.map((w, i) => (
              <span key={i} className="loom-dp-dow-cell">{w}</span>
            ))}
          </div>
          <div className="loom-dp-grid">
            {cells.map((d, i) => {
              if (!d) return <span key={i} className="loom-dp-cell empty" aria-hidden="true" />;
              const iso = toISO(d);
              return (
                <button
                  key={i}
                  type="button"
                  className={`loom-dp-cell${iso === value ? " on" : ""}${iso === todayISO ? " today" : ""}`}
                  aria-current={iso === todayISO ? "date" : undefined}
                  onClick={() => pick(d)}
                >
                  {d.getDate()}
                </button>
              );
            })}
          </div>
          <div className="loom-dp-foot">
            <button type="button" className="loom-dp-link" onClick={() => pick(new Date())}>
              {t("今天", "Today")}
            </button>
            {value ? (
              <button
                type="button"
                className="loom-dp-link"
                onClick={() => {
                  onChange("");
                  setOpen(false);
                }}
              >
                {t("清除", "Clear")}
              </button>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}
