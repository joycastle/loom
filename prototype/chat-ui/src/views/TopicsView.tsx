// Faithful React port of browse.html's Topics view — the DAG topic graph.
// Mirrors loadTopics()/pick()/groups() from loom/assets/browse.html: a hand-laid
// SVG directed-acyclic-graph with curved connector edges, gold parent / teal leaf
// nodes, per-node count badges, a ↺ marker for multi-parent nodes, and a
// click→subtree-rollup members panel. DOM structure + class names match
// browse.html so the ported browse.css styles it identically.
import { useEffect, useMemo, useState } from "react";
import { useLoom } from "@/runtime/LoomProvider";
import { RecordCard, kindLabel } from "@/components/RecordDrawer";
import { useT } from "@/lib/lang";
import type { LoomCard, LoomTopicResponse } from "@/types/loom";

// browse.html: KIND map + groups() ordering.
const KIND: Record<string, string> = {
  session: "💬",
  commit: "💻",
  doc: "📄",
  note: "📎",
  report: "📋",
  requirement: "📥",
};
const GROUP_ORDER = ["report", "session", "commit", "doc", "note", "requirement"];

// A flat graph node as returned by /api/topics (nodes: [{name,count,direct,multi}]).
type TNode = { name: string; count: number; direct?: number; multi?: boolean };
// A nested tree node (used only for the mock/tree-fallback path).
type TreeNode = { name: string; count?: number; multi?: boolean; children?: TreeNode[] };
// browse.html shape of /api/topics. The shared LoomTopicsResponse type declares
// nodes/edges as numbers (mock), so we cast to this and normalise below.
type RawTopics = {
  tree?: TreeNode[];
  nodes?: TNode[] | number;
  edges?: [string, string][] | number;
  loose?: string[];
  total_tagged?: number;
};

// browse.html NW(n): node box width from label chars (CJK=14px, ascii=8px),
// count digits, the ↺ marker, and padding.
function NW(n: TNode): number {
  let w = 14;
  for (const ch of n.name) w += ch.charCodeAt(0) > 255 ? 14 : 8;
  return w + String(n.count).length * 7.5 + (n.multi ? 16 : 0) + 22;
}

// Normalise /api/topics into flat nodes + edges. Primary path uses the arrays
// the real backend returns; falls back to flattening `tree` (mock client returns
// numeric nodes/edges plus a nested tree).
function normalize(raw: RawTopics): { nodes: TNode[]; edges: [string, string][] } {
  if (Array.isArray(raw.nodes)) {
    return { nodes: raw.nodes, edges: Array.isArray(raw.edges) ? raw.edges : [] };
  }
  const nodes = new Map<string, TNode>();
  const edges: [string, string][] = [];
  const seen = new Set<string>();
  const walk = (n: TreeNode, parent: string | null) => {
    if (!nodes.has(n.name)) {
      nodes.set(n.name, { name: n.name, count: n.count ?? 0, multi: n.multi });
    }
    if (parent) {
      const k = `${parent}|${n.name}`;
      if (!seen.has(k)) {
        seen.add(k);
        edges.push([parent, n.name]);
      }
    }
    (n.children || []).forEach((c) => walk(c, n.name));
  };
  (raw.tree || []).forEach((n) => walk(n, null));
  return { nodes: [...nodes.values()], edges };
}

type EdgeGeom = { p: string; c: string; d: string };
type NodeGeom = { n: TNode; x: number; y: number; w: number; heat: number; root: boolean; cw: number };
type Layout = { W: number; H: number; edges: EdgeGeom[]; nodes: NodeGeom[] };

// Port of loadTopics()'s layout math + SVG geometry.
function buildLayout(nodes: TNode[], edges: [string, string][]): Layout {
  const byN: Record<string, TNode> = {};
  nodes.forEach((n) => (byN[n.name] = n));

  const parents: Record<string, string[]> = {};
  edges.forEach(([p, c]) => (parents[c] = parents[c] || []).push(p));

  // depth = longest parent chain (with cycle protection).
  const depth: Record<string, number> = {};
  const dep = (name: string, seenSet: Set<string>): number => {
    if (depth[name] != null) return depth[name];
    if (seenSet.has(name)) return 0;
    seenSet.add(name);
    const ps = (parents[name] || []).filter((p) => byN[p]);
    return (depth[name] = ps.length ? 1 + Math.max(...ps.map((p) => dep(p, seenSet))) : 0);
  };
  nodes.forEach((n) => dep(n.name, new Set()));

  const cols: TNode[][] = [];
  nodes.forEach((n) => (cols[depth[n.name]] = cols[depth[n.name]] || []).push(n));

  const pos: Record<string, { x: number; y: number }> = {};
  const rowH = 48;
  const padY = 14;
  const colX: number[] = [];
  let x = 12;
  cols.forEach((col, ci) => {
    colX[ci] = x;
    x += Math.max(...col.map(NW)) + 72;
  });
  // Each column: order by mean-parent-y to reduce crossings; fall back to count.
  cols.forEach((col, ci) => {
    const avgY = (n: TNode) => {
      const ps = (parents[n.name] || [])
        .map((p) => pos[p] && pos[p].y)
        .filter((v): v is number => v != null);
      return ps.length ? ps.reduce((a, b) => a + b, 0) / ps.length : 1e9;
    };
    col.sort((a, b) => {
      const ay = avgY(a);
      const by = avgY(b);
      return ay - by || b.count - a.count;
    });
    col.forEach((n, i) => (pos[n.name] = { x: colX[ci], y: padY + i * rowH }));
  });

  const H = Math.max(...cols.map((c) => c.length)) * rowH + padY * 2;
  const W = x;
  const maxC = Math.max(...nodes.map((n) => n.count || 1));

  const edgeGeom: EdgeGeom[] = [];
  for (const [p, c] of edges) {
    if (!pos[p] || !pos[c]) continue;
    const x1 = pos[p].x + NW(byN[p]);
    const y1 = pos[p].y + 16;
    const x2 = pos[c].x;
    const y2 = pos[c].y + 16;
    const mx = (x1 + x2) / 2;
    edgeGeom.push({ p, c, d: `M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}` });
  }

  const nodeGeom: NodeGeom[] = nodes.map((n) => {
    const { x: nx, y: ny } = pos[n.name];
    const w = NW(n);
    // heat底色:上卷越多越暖.
    const heat = Math.min(0.3, 0.05 + 0.25 * (n.count / maxC));
    const root = depth[n.name] === 0;
    const cw = String(n.count).length * 7.5 + 12;
    return { n, x: nx, y: ny, w, heat, root, cw };
  });

  return { W, H, edges: edgeGeom, nodes: nodeGeom };
}

// Port of browse.html groups(g): union of ordered kinds + any extras, each a
// .gh header + its cards. Cards use RecordCard (opens the detail drawer).
function MemberGroups({ groups }: { groups: Record<string, LoomCard[]> }) {
  const t = useT();
  const keys = [
    ...new Set([...GROUP_ORDER.filter((k) => groups[k]), ...Object.keys(groups)]),
  ];
  // Per-kind collapse (controlled — a native <details> toggles unreliably in the
  // desktop WebView). All groups start expanded.
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const toggle = (k: string) =>
    setCollapsed((prev) => {
      const next = new Set(prev);
      next.has(k) ? next.delete(k) : next.add(k);
      return next;
    });
  if (!keys.length) return <div className="empty">{t("空", "Empty")}</div>;
  return (
    <>
      {keys.map((k) => {
        const open = !collapsed.has(k);
        return (
          <div key={k}>
            <button
              type="button"
              className="gh gh-fold"
              aria-expanded={open}
              onClick={() => toggle(k)}
            >
              <span className="gh-caret" aria-hidden="true">{open ? "▾" : "▸"}</span>
              {KIND[k] || ""} {kindLabel(t, k)} ({groups[k].length})
            </button>
            {open
              ? groups[k].map((card) => <RecordCard key={card.id} card={card} />)
              : null}
          </div>
        );
      })}
    </>
  );
}

export function TopicsView() {
  const t = useT();
  const { ledger } = useLoom();
  const [raw, setRaw] = useState<RawTopics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [member, setMember] = useState<LoomTopicResponse | null>(null);
  const [memberLoading, setMemberLoading] = useState(false);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(false);
    ledger
      .topics()
      .then((data) => {
        if (!alive) return;
        setRaw(data as unknown as RawTopics);
      })
      .catch(() => alive && setError(true))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [ledger]);

  const graph = useMemo(() => {
    if (!raw) return null;
    const { nodes, edges } = normalize(raw);
    if (!nodes.length) return null;
    return { layout: buildLayout(nodes, edges), count: nodes.length };
  }, [raw]);

  // pick(name): highlight the node + its edges, then load its rolled-up members.
  const pick = (name: string) => {
    setSelected(name);
    setMember(null);
    setMemberLoading(true);
    ledger
      .topic(name)
      .then((r) => setMember(r))
      .catch(() => setMember(null))
      .finally(() => setMemberLoading(false));
  };

  const loose = raw?.loose ?? [];
  const totalTagged = raw?.total_tagged ?? 0;

  return (
    <>
      <div id="tgraph">
        {loading ? (
          <div className="empty">{t("加载中…", "Loading…")}</div>
        ) : error ? (
          <div className="empty">{t("主题图加载失败，请稍后重试。", "The topic graph failed to load. Please try again later.")}</div>
        ) : !graph ? (
          <div className="empty">
            {t("还没有主题。同步记录并完成归类后，主题关系会显示在这里。", "No topics yet. After syncing and classifying records, topic relationships appear here.")}
          </div>
        ) : (
          <svg
            viewBox={`0 0 ${graph.layout.W} ${graph.layout.H}`}
            width={graph.layout.W}
            height={graph.layout.H}
          >
            <defs>
              <filter id="sh" x="-20%" y="-20%" width="140%" height="160%">
                <feDropShadow dx="0" dy="2" stdDeviation="3" floodColor="#000" floodOpacity="0.35" />
              </filter>
            </defs>
            {graph.layout.edges.map((e) => (
              <path
                key={`${e.p}|${e.c}`}
                className={`gedge${selected && (e.p === selected || e.c === selected) ? " hl" : ""}`}
                data-e={`${e.p}|${e.c}`}
                d={e.d}
              />
            ))}
            {graph.layout.nodes.map(({ n, x, y, w, heat, root, cw }) => (
              <g
                key={n.name}
                className={`gnode${selected === n.name ? " on" : ""}`}
                data-n={n.name}
                transform={`translate(${x},${y})`}
                onClick={() => pick(n.name)}
              >
                <rect
                  width={w}
                  height={32}
                  rx={16}
                  ry={16}
                  fill={`rgba(224,168,78,${heat.toFixed(2)})`}
                  stroke={root ? "#8a6320" : "var(--line)"}
                  filter="url(#sh)"
                />
                <text x={13} y={21}>
                  {n.name}
                  {n.multi ? " ↺" : ""}
                </text>
                <rect
                  x={w - cw - 7}
                  y={8}
                  width={cw}
                  height={16}
                  rx={8}
                  fill={root ? "#E0A84E" : "#5AA9A0"}
                  opacity={0.9}
                />
                <text className="cnt" x={w - cw / 2 - 7} y={20} textAnchor="middle">
                  {n.count}
                </text>
              </g>
            ))}
          </svg>
        )}
      </div>

      <div className="loose" id="tloose">
        {graph ? (
          <>
            {loose.length ? (
              <>
                {t("未建页:", "No page yet: ")}
                {loose.map((name, i) => (
                  <span key={name}>
                    {i ? " · " : ""}
                    <b onClick={() => pick(name)}>{name}</b>
                  </span>
                ))}
                {" · "}
              </>
            ) : null}
            {t(`已归类 ${totalTagged} 条 · ↺=多父(DAG)`, `${totalTagged} classified · ↺ = multi-parent (DAG)`)}
          </>
        ) : null}
      </div>

      <div id="tmembers">
        {member ? (
          <>
            <div className="gh gh-topic" style={{ fontSize: 15 }}>
              🧵 {member.name} · {t(`上卷 ${member.total} 条`, `${member.total} rolled up`)}
              {member.parents?.length ? (
                <span style={{ color: "var(--dim)" }}>
                  {" · "}
                  {t("父主题", "parent")}: {member.parents.join(", ")}
                </span>
              ) : null}
            </div>
            <MemberGroups groups={member.groups} />
          </>
        ) : memberLoading ? (
          <div className="empty">{t("加载中…", "Loading…")}</div>
        ) : (
          <div className="empty">{t("↑ 点图里的主题节点,看这件事的全景(含子树上卷)", "↑ Click a topic node to see everything about it (subtree rolled up)")}</div>
        )}
      </div>
    </>
  );
}
