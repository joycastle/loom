// Topics combines two complementary views: a collapsible family summary for
// hierarchy and an aggregate matrix for cross-topic relations. Both feed the
// same click→subtree-rollup members panel.
import { useEffect, useMemo, useState } from "react";
import type { CSSProperties } from "react";
import { useLoom } from "@/runtime/LoomProvider";
import { RecordCard, kindLabel } from "@/components/RecordDrawer";
import { useT } from "@/lib/lang";
import type {
  LoomCard,
  LoomTopicRelationGraph,
  LoomTopicRelationNode,
  LoomTopicResponse,
} from "@/types/loom";

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
      const k = JSON.stringify([parent, n.name]);
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

type TopicMatrixNode = LoomTopicRelationNode & {
  depth: number;
  familyIndex: number;
  familyRoot: string;
  root: boolean;
};

type PrimaryTopicHierarchy = {
  primaryParent: Map<string, string>;
  children: Map<string, string[]>;
};

function topicPairKey(left: string, right: string): string {
  const pair = left <= right ? [left, right] : [right, left];
  return JSON.stringify(pair);
}

function buildPrimaryTopicHierarchy(graph: LoomTopicRelationGraph): PrimaryTopicHierarchy {
  const byName = new Map(graph.nodes.map((node) => [node.name, node]));
  const parents = new Map<string, string[]>();
  for (const [parent, child] of graph.hierarchy_edges) {
    if (!byName.has(parent) || !byName.has(child)) continue;
    parents.set(child, [...(parents.get(child) || []), parent]);
  }
  const primaryParent = new Map<string, string>();
  for (const [child, names] of parents) {
    const ranked = [...names].sort((left, right) =>
      (byName.get(right)?.count || 0) - (byName.get(left)?.count || 0) ||
      left.localeCompare(right));
    if (ranked[0]) primaryParent.set(child, ranked[0]);
  }
  const children = new Map<string, string[]>();
  for (const [child, parent] of primaryParent) {
    children.set(parent, [...(children.get(parent) || []), child]);
  }
  for (const [parent, names] of children) {
    children.set(parent, names.sort((left, right) =>
      (byName.get(right)?.count || 0) - (byName.get(left)?.count || 0) ||
      left.localeCompare(right)));
  }
  return { primaryParent, children };
}

function visibleTopicGraph(
  graph: LoomTopicRelationGraph,
  expandedParents: Set<string>,
  hierarchy: PrimaryTopicHierarchy,
): LoomTopicRelationGraph {
  const { primaryParent, children } = hierarchy;
  const visible = new Set(graph.nodes.filter((node) => !primaryParent.has(node.name)).map((node) => node.name));
  const queue = [...visible];
  while (queue.length) {
    const parent = queue.shift() as string;
    if (!expandedParents.has(parent)) continue;
    for (const child of children.get(parent) || []) {
      if (visible.has(child)) continue;
      visible.add(child);
      queue.push(child);
    }
  }
  const representative = (name: string): string | null => {
    let current: string | undefined = name;
    const seen = new Set<string>();
    while (current && !seen.has(current)) {
      if (visible.has(current)) return current;
      seen.add(current);
      current = primaryParent.get(current);
    }
    return null;
  };
  const relationAcc = new Map<string, LoomTopicRelationGraph["relation_edges"][number]>();
  for (const edge of graph.relation_edges) {
    const left = representative(edge.source);
    const right = representative(edge.target);
    if (!left || !right) continue;
    const [source, target] = left <= right ? [left, right] : [right, left];
    const key = topicPairKey(source, target);
    const current = relationAcc.get(key);
    if (current) {
      current.count += edge.count;
      current.score += edge.score;
      current.reasons = [...new Set([...current.reasons, ...edge.reasons])].slice(0, 3);
    } else {
      relationAcc.set(key, { source, target, count: edge.count, score: edge.score, reasons: [...edge.reasons] });
    }
  }
  const relationEdges = [...relationAcc.values()]
    .map((edge) => ({ ...edge, score: Math.round(edge.score * 1000) / 1000 }))
    .sort((left, right) => right.count - left.count || right.score - left.score ||
      left.source.localeCompare(right.source) || left.target.localeCompare(right.target));
  return {
    ...graph,
    nodes: graph.nodes.filter((node) => visible.has(node.name)),
    hierarchy_edges: graph.hierarchy_edges.filter(([parent, child]) =>
      primaryParent.get(child) === parent &&
      visible.has(parent) && visible.has(child) && expandedParents.has(parent)),
    relation_edges: relationEdges,
  };
}

function buildTopicMatrixNodes(
  graph: LoomTopicRelationGraph,
  visibleGraph: LoomTopicRelationGraph,
  hierarchy: PrimaryTopicHierarchy,
): TopicMatrixNode[] {
  const { primaryParent } = hierarchy;
  const roots = graph.nodes
    .filter((node) => !primaryParent.has(node.name))
    .sort((left, right) => right.count - left.count || left.name.localeCompare(right.name));
  const rootOrder = new Map(roots.map((node, index) => [node.name, index]));
  const info = new Map<string, { familyRoot: string; depth: number }>();
  const resolve = (name: string, seen = new Set<string>()): { familyRoot: string; depth: number } => {
    const cached = info.get(name);
    if (cached) return cached;
    if (seen.has(name)) return { familyRoot: name, depth: 0 };
    const parent = primaryParent.get(name);
    if (!parent) {
      const rootInfo = { familyRoot: name, depth: 0 };
      info.set(name, rootInfo);
      return rootInfo;
    }
    const parentInfo = resolve(parent, new Set(seen).add(name));
    const result = { familyRoot: parentInfo.familyRoot, depth: parentInfo.depth + 1 };
    info.set(name, result);
    return result;
  };
  return visibleGraph.nodes.map((node) => {
    const nodeInfo = resolve(node.name);
    return {
      ...node,
      ...nodeInfo,
      root: node.name === nodeInfo.familyRoot,
      familyIndex: (rootOrder.get(nodeInfo.familyRoot) ?? 0) % 8,
    };
  });
}

type TopicSummaryModel = {
  byName: Map<string, TNode>;
  roots: string[];
  children: Map<string, string[]>;
  parents: Map<string, string[]>;
};

type TopicTreeNodeGeom = {
  node: TNode;
  name: string;
  x: number;
  y: number;
  depth: number;
  familyIndex: number;
  childCount: number;
  open: boolean;
};

type TopicTreeEdgeGeom = {
  parent: string;
  child: string;
  d: string;
  familyIndex: number;
};

type TopicTreeLayout = {
  width: number;
  height: number;
  nodes: TopicTreeNodeGeom[];
  edges: TopicTreeEdgeGeom[];
};

const TOPIC_TREE_NODE_W = 196;
const TOPIC_TREE_NODE_H = 56;
const TOPIC_TREE_LEVEL_GAP = 78;
const TOPIC_TREE_ROW_GAP = 18;
const TOPIC_TREE_ROOT_GAP = 30;

function buildTopicSummaryModel(nodes: TNode[], edges: [string, string][]): TopicSummaryModel {
  const byName = new Map(nodes.map((node) => [node.name, node]));
  const parents = new Map<string, string[]>();
  for (const [parent, child] of edges) {
    if (!byName.has(parent) || !byName.has(child)) continue;
    parents.set(child, [...(parents.get(child) || []), parent]);
  }
  const primaryParent = new Map<string, string>();
  for (const [child, names] of parents) {
    const ranked = [...names].sort((left, right) =>
      (byName.get(right)?.count || 0) - (byName.get(left)?.count || 0) ||
      left.localeCompare(right));
    if (ranked[0]) primaryParent.set(child, ranked[0]);
  }
  const children = new Map<string, string[]>();
  for (const [child, parent] of primaryParent) {
    children.set(parent, [...(children.get(parent) || []), child]);
  }
  for (const [parent, names] of children) {
    children.set(parent, names.sort((left, right) =>
      (byName.get(right)?.count || 0) - (byName.get(left)?.count || 0) ||
      left.localeCompare(right)));
  }
  const roots = nodes
    .filter((node) => !primaryParent.has(node.name))
    .sort((left, right) => right.count - left.count || left.name.localeCompare(right.name))
    .map((node) => node.name);
  return { byName, roots, children, parents };
}

function compactTopicLabel(name: string, maxUnits = 24): string {
  let units = 0;
  let result = "";
  for (const char of name) {
    const width = char.charCodeAt(0) > 255 ? 2 : 1;
    if (units + width > maxUnits) return result + "…";
    result += char;
    units += width;
  }
  return result;
}

function buildTopicTreeLayout(model: TopicSummaryModel, expandedTopics: Set<string>): TopicTreeLayout {
  const positions = new Map<string, TopicTreeNodeGeom>();
  let cursorY = 18;
  let maxDepth = 0;

  const place = (name: string, depth: number, familyIndex: number, ancestors: Set<string>): number => {
    const node = model.byName.get(name);
    if (!node) return cursorY;
    const allChildren = model.children.get(name) || [];
    const open = allChildren.length > 0 && expandedTopics.has(name);
    const visibleChildren = open ? allChildren.filter((child) => !ancestors.has(child)) : [];
    let centerY: number;
    if (visibleChildren.length) {
      const nextAncestors = new Set(ancestors).add(name);
      const childCenters = visibleChildren.map((child) => place(child, depth + 1, familyIndex, nextAncestors));
      centerY = (childCenters[0] + childCenters[childCenters.length - 1]) / 2;
    } else {
      centerY = cursorY + TOPIC_TREE_NODE_H / 2;
      cursorY += TOPIC_TREE_NODE_H + TOPIC_TREE_ROW_GAP;
    }
    maxDepth = Math.max(maxDepth, depth);
    positions.set(name, {
      node,
      name,
      x: 18 + depth * (TOPIC_TREE_NODE_W + TOPIC_TREE_LEVEL_GAP),
      y: centerY - TOPIC_TREE_NODE_H / 2,
      depth,
      familyIndex,
      childCount: allChildren.length,
      open,
    });
    return centerY;
  };

  model.roots.forEach((root, index) => {
    place(root, 0, index % 8, new Set());
    cursorY += TOPIC_TREE_ROOT_GAP - TOPIC_TREE_ROW_GAP;
  });

  const edges: TopicTreeEdgeGeom[] = [];
  for (const parent of positions.values()) {
    if (!parent.open) continue;
    for (const childName of model.children.get(parent.name) || []) {
      const child = positions.get(childName);
      if (!child) continue;
      const x1 = parent.x + TOPIC_TREE_NODE_W;
      const y1 = parent.y + TOPIC_TREE_NODE_H / 2;
      const x2 = child.x;
      const y2 = child.y + TOPIC_TREE_NODE_H / 2;
      const bend = Math.max(32, (x2 - x1) * 0.48);
      edges.push({
        parent: parent.name,
        child: child.name,
        familyIndex: parent.familyIndex,
        d: `M${x1},${y1} C${x1 + bend},${y1} ${x2 - bend},${y2} ${x2},${y2}`,
      });
    }
  }

  return {
    width: Math.max(760, 36 + (maxDepth + 1) * TOPIC_TREE_NODE_W + maxDepth * TOPIC_TREE_LEVEL_GAP),
    height: Math.max(260, cursorY - TOPIC_TREE_ROW_GAP + 18),
    nodes: [...positions.values()].sort((left, right) => left.depth - right.depth || left.y - right.y),
    edges,
  };
}

function TopicSummary({ nodes, edges, selected, onPick }: {
  nodes: TNode[];
  edges: [string, string][];
  selected: string | null;
  onPick: (name: string) => void;
}) {
  const t = useT();
  const [expandedTopics, setExpandedTopics] = useState<Set<string>>(new Set());
  const model = useMemo(() => buildTopicSummaryModel(nodes, edges), [nodes, edges]);
  const layout = useMemo(() => buildTopicTreeLayout(model, expandedTopics), [model, expandedTopics]);
  const toggle = (name: string) => setExpandedTopics((current) => {
    if (!(model.children.get(name) || []).length) return current;
    const next = new Set(current);
    if (next.has(name)) {
      const subtree = [name];
      while (subtree.length) {
        const topic = subtree.pop() as string;
        next.delete(topic);
        subtree.push(...(model.children.get(topic) || []));
      }
    } else {
      next.add(name);
    }
    return next;
  });

  return (
    <>
      <div className="topic-summary-meta">
        <span><strong>{model.roots.length}</strong>{t(" 个主题族", " topic families")}</span>
        <span><strong>{layout.nodes.length}/{nodes.length}</strong>{t(" 个当前可见主题", " visible topics")}</span>
        <span><strong>{layout.edges.length}/{edges.length}</strong>{t(" 条当前层级线", " visible hierarchy links")}</span>
        <span>{t("默认仅顶层；双击节点展开或收起子树", "roots only by default; double-click a node to expand or collapse its subtree")}</span>
      </div>
      <div className="topic-tree-wrap">
        <svg
          className="topic-tree"
          viewBox={`0 0 ${layout.width} ${layout.height}`}
          width={layout.width}
          height={layout.height}
          role="tree"
          aria-label={t("主题层级树", "Topic hierarchy tree")}
        >
          <title>{t("主题层级树", "Topic hierarchy tree")}</title>
          <desc>{t("默认显示顶层主题，双击有子主题的节点逐层展开。", "Top-level topics are shown by default. Double-click a node with children to expand it level by level.")}</desc>
          {layout.edges.map((edge) => (
            <path
              key={edge.parent + "→" + edge.child}
              className="topic-tree-edge"
              d={edge.d}
              style={{ "--topic-color": "var(--topic-family-" + edge.familyIndex + ")" } as CSSProperties}
            />
          ))}
          {layout.nodes.map((item) => {
            const parentCount = (model.parents.get(item.name) || []).length;
            const direct = item.node.direct ?? item.node.count;
            return (
              <g
                key={item.name}
                className={"topic-tree-node" + (selected === item.name ? " selected" : "")}
                style={{ "--topic-color": "var(--topic-family-" + item.familyIndex + ")" } as CSSProperties}
                transform={`translate(${item.x} ${item.y})`}
                role="treeitem"
                tabIndex={0}
                aria-expanded={item.childCount ? item.open : undefined}
                aria-label={item.name + "，" + item.node.count + t(" 条记录", " records")}
                onClick={() => onPick(item.name)}
                onDoubleClick={() => toggle(item.name)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    onPick(item.name);
                  } else if (event.key === "ArrowRight" && item.childCount && !item.open) {
                    event.preventDefault();
                    toggle(item.name);
                  } else if (event.key === "ArrowLeft" && item.childCount && item.open) {
                    event.preventDefault();
                    toggle(item.name);
                  }
                }}
              >
                <title>{item.name + " · " + t("上卷 ", "rolled up ") + item.node.count + " · " + t("直挂 ", "direct ") + direct}</title>
                <rect className="topic-tree-card" width={TOPIC_TREE_NODE_W} height={TOPIC_TREE_NODE_H} rx={10} />
                <rect className="topic-tree-family-mark" width={4} height={TOPIC_TREE_NODE_H - 14} x={0} y={7} rx={2} />
                <text className="topic-tree-name" x={14} y={21}>
                  {compactTopicLabel(item.name)}{parentCount > 1 ? " ↺" + parentCount : ""}
                </text>
                <rect className="topic-tree-count-bg" x={TOPIC_TREE_NODE_W - 48} y={8} width={36} height={19} rx={9.5} />
                <text className="topic-tree-count" x={TOPIC_TREE_NODE_W - 30} y={21.5} textAnchor="middle">{item.node.count}</text>
                <text className="topic-tree-subline" x={14} y={43}>
                  {item.childCount
                    ? (item.open ? "▾ " : "▸ ") + t(item.childCount + " 个子主题", item.childCount + " children")
                    : t("叶主题", "leaf topic")}
                </text>
                {direct !== item.node.count ? (
                  <text className="topic-tree-direct" x={TOPIC_TREE_NODE_W - 13} y={43} textAnchor="end">
                    {t("直挂 ", "direct ")}{direct}
                  </text>
                ) : null}
              </g>
            );
          })}
        </svg>
      </div>
    </>
  );
}

function RelationOverview({ selected, onPick }: {
  selected: string | null;
  onPick: (name: string) => void;
}) {
  const t = useT();
  const { ledger } = useLoom();
  const [data, setData] = useState<LoomTopicRelationGraph | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [expandedParents, setExpandedParents] = useState<Set<string>>(new Set());
  const [focusedRelationKey, setFocusedRelationKey] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(false);
    ledger.topicRelations()
      .then((result) => alive && setData(result))
      .catch(() => alive && setError(true))
      .finally(() => alive && setLoading(false));
    return () => { alive = false; };
  }, [ledger]);

  const primaryHierarchy = useMemo(
    () => data ? buildPrimaryTopicHierarchy(data) : null,
    [data],
  );
  const visibleGraph = useMemo(
    () => data && primaryHierarchy
      ? visibleTopicGraph(data, expandedParents, primaryHierarchy)
      : null,
    [data, expandedParents, primaryHierarchy],
  );
  const childrenByTopic = primaryHierarchy?.children;
  const matrixNodes = useMemo(() => {
    if (!data || !visibleGraph || !primaryHierarchy) return [];
    const nodes = buildTopicMatrixNodes(data, visibleGraph, primaryHierarchy);
    const roots = nodes
      .filter((node) => node.root)
      .sort((left, right) => right.count - left.count || left.name.localeCompare(right.name));
    const familyOrder = new Map(roots.map((node, index) => [node.name, index]));
    return nodes.sort((left, right) =>
      Number(right.root) - Number(left.root) ||
      (left.root && right.root ? right.count - left.count || left.name.localeCompare(right.name) : 0) ||
      (familyOrder.get(left.familyRoot) ?? 999) - (familyOrder.get(right.familyRoot) ?? 999) ||
      left.depth - right.depth ||
      right.count - left.count ||
      left.name.localeCompare(right.name));
  }, [data, visibleGraph, primaryHierarchy]);
  const familyByTopic = useMemo(
    () => new Map(matrixNodes.map((node) => [node.name, node.familyRoot])),
    [matrixNodes],
  );
  const relationByKey = useMemo(() => {
    const result = new Map<string, LoomTopicRelationGraph["relation_edges"][number]>();
    for (const edge of visibleGraph?.relation_edges || []) {
      const key = topicPairKey(edge.source, edge.target);
      result.set(key, edge);
    }
    return result;
  }, [visibleGraph]);
  const crossFamilyRelations = useMemo(
    () => (visibleGraph?.relation_edges || []).filter((edge) =>
      edge.source !== edge.target &&
      familyByTopic.get(edge.source) !== familyByTopic.get(edge.target)),
    [visibleGraph, familyByTopic],
  );
  const maxCrossFamilyCount = Math.max(1, ...crossFamilyRelations.map((edge) => edge.count));
  const maxSameFamilyCount = Math.max(1, ...(visibleGraph?.relation_edges || [])
    .filter((edge) => familyByTopic.get(edge.source) === familyByTopic.get(edge.target))
    .map((edge) => edge.count));
  const selectedNode = selected ? data?.nodes.find((node) => node.name === selected) : null;
  const selectedChildCount = selected ? (childrenByTopic?.get(selected) || []).length : 0;
  const selectedRelation = focusedRelationKey ? relationByKey.get(focusedRelationKey) : null;
  const familyCount = new Set(matrixNodes.map((node) => node.familyRoot)).size;
  const displayName = (node: TopicMatrixNode) =>
    expandedParents.has(node.name) ? node.name + " · 本级" : node.name;
  const displayCount = (node: TopicMatrixNode) =>
    expandedParents.has(node.name) ? node.direct : node.count;
  const compactCount = (value: number) => value >= 1000
    ? (value / 1000).toFixed(value >= 10000 ? 0 : 1).replace(/\.0$/, "") + "k"
    : String(value);
  const toggleChildren = (name: string) => {
    if (!(childrenByTopic?.get(name) || []).length) return;
    setFocusedRelationKey(null);
    setExpandedParents((current) => {
      const next = new Set(current);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  };

  if (loading) return <div className="empty">{t("加载主题关联…", "Loading topic relations…")}</div>;
  if (error) return <div className="empty">{t("主题关联加载失败。", "Topic relations failed to load.")}</div>;
  if (!data || !visibleGraph || !matrixNodes.length) {
    return <div className="empty">{t("还没有主题或可聚合的关系。", "No topics or aggregate relations yet.")}</div>;
  }

  return (
    <>
      <div className="topic-relation-meta">
        <span><strong>{matrixNodes.length}/{data.nodes.length}</strong>{t(" 个当前可见主题", " visible topics")}</span>
        <span><strong>{familyCount}</strong>{t(" 个主题族", " topic families")}</span>
        <span><strong>{crossFamilyRelations.length}/{visibleGraph.relation_edges.length}</strong>{t(" 条跨主题族 / 当前聚合单元", " cross-family / current aggregate cells")}</span>
        <span><strong>{data.total_relation_edges}</strong>{t(" 条记录关系", " record links")}</span>
        <span><strong>{data.mapped_relation_edges}</strong>{t(" 条进入主题聚合", " mapped across topics")}</span>
      </div>
      <div id="topic-relation-overview" className="topic-association-wrap">
        <table className="topic-association-matrix">
          <caption className="sr-only">{t("主题聚合关联矩阵", "Aggregate topic relation matrix")}</caption>
          <thead>
            <tr>
              <th className="topic-matrix-corner" scope="col">
                <span>{t("主题", "Topic")}</span>
                <small>{t("关联到 →", "relates to →")}</small>
              </th>
              {matrixNodes.map((node) => {
                const childCount = (childrenByTopic?.get(node.name) || []).length;
                const focused = Boolean(
                  selectedRelation &&
                  (selectedRelation.source === node.name || selectedRelation.target === node.name)
                );
                return (
                  <th
                    key={"column:" + node.name}
                    className={
                      "topic-matrix-column" +
                      (node.root ? " root" : "") +
                      (focused ? " focused" : "")
                    }
                    scope="col"
                    style={{ "--topic-color": "var(--topic-family-" + node.familyIndex + ")" } as CSSProperties}
                  >
                    <span className="topic-matrix-family-mark" />
                    <span>{displayName(node)}{node.multi ? " ↺" : ""}</span>
                    <small>
                      {childCount ? childCount + t(" 子 · ", " children · ") : ""}
                      {displayCount(node)}
                    </small>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {matrixNodes.map((row, rowIndex) => {
              const childCount = (childrenByTopic?.get(row.name) || []).length;
              const rowFocused = Boolean(
                selectedRelation &&
                (selectedRelation.source === row.name || selectedRelation.target === row.name)
              );
              return (
                <tr
                  key={"row:" + row.name}
                  className={
                    (row.root ? "topic-matrix-family-start" : "") +
                    (rowFocused ? " focused" : "")
                  }
                >
                  <th scope="row">
                    <div
                      className={
                        "topic-matrix-row-label" +
                        (row.root ? " root" : "") +
                        (selected === row.name ? " selected" : "")
                      }
                      style={{ "--topic-color": "var(--topic-family-" + row.familyIndex + ")" } as CSSProperties}
                    >
                      <span className="topic-matrix-family-mark" />
                      <button
                        type="button"
                        className="topic-matrix-row-name"
                        aria-label={t("查看主题 " + row.name, "View topic " + row.name)}
                        onClick={() => {
                          setFocusedRelationKey(null);
                          onPick(row.name);
                        }}
                        onDoubleClick={() => toggleChildren(row.name)}
                      >
                        {row.depth ? "↳ " : ""}{displayName(row)}{row.multi ? " ↺" : ""}
                      </button>
                      {childCount ? (
                        <button
                          type="button"
                          className="topic-matrix-child-count"
                          aria-expanded={expandedParents.has(row.name)}
                          aria-label={expandedParents.has(row.name)
                            ? t("收起 " + row.name + " 的 " + childCount + " 个子主题", "Collapse " + childCount + " children of " + row.name)
                            : t("展开 " + row.name + " 的 " + childCount + " 个子主题", "Expand " + childCount + " children of " + row.name)}
                          onClick={() => toggleChildren(row.name)}
                        >
                          {expandedParents.has(row.name) ? "▾" : "▸"}{childCount}
                        </button>
                      ) : null}
                      <span className="topic-matrix-node-count">{displayCount(row)}</span>
                    </div>
                  </th>
                  {matrixNodes.map((column, columnIndex) => {
                    const key = topicPairKey(row.name, column.name);
                    const relation = relationByKey.get(key);
                    const internal = row.name === column.name;
                    const sameFamily = row.familyRoot === column.familyRoot;
                    const mirror = rowIndex > columnIndex;
                    if (!relation) {
                      return (
                        <td
                          key={key}
                          className={
                            "topic-matrix-cell empty" +
                            (mirror ? " mirror" : "") +
                            (internal ? " internal" : "") +
                            (sameFamily ? " same-family" : "")
                          }
                          aria-hidden={mirror || undefined}
                          aria-label={mirror ? undefined : internal
                            ? t(row.name + " 当前折叠范围内部无聚合关联", row.name + " has no internal aggregate relation in the current collapsed scope")
                            : t(row.name + " 与 " + column.name + " 暂无关联", "No relation between " + row.name + " and " + column.name)}
                        />
                      );
                    }
                    const scaleMax = sameFamily ? maxSameFamilyCount : maxCrossFamilyCount;
                    const strength = Math.round(
                      (sameFamily ? 8 : 12) +
                      (sameFamily ? 16 : 32) * Math.log1p(relation.count) / Math.log1p(scaleMax)
                    );
                    const active = focusedRelationKey === key;
                    const relationClassName =
                      "topic-matrix-relation" +
                      (mirror ? " mirror-mark" : "") +
                      (internal ? " internal" : "") +
                      (active ? " selected" : "");
                    const relationStyle = {
                      "--relation-left": "var(--topic-family-" + row.familyIndex + ")",
                      "--relation-right": "var(--topic-family-" + column.familyIndex + ")",
                      "--relation-strength": strength + "%",
                    } as CSSProperties;
                    const relationLabel = internal
                      ? t(
                        row.name + " 当前折叠范围内部聚合关联 " + relation.count,
                        row.name + " internal aggregate relation in the current collapsed scope: " + relation.count
                      )
                      : t(
                        row.name + " 与 " + column.name + "：主题对关联 " + relation.count,
                        row.name + " and " + column.name + ": " + relation.count + " topic-pair relations"
                      );
                    return (
                      <td
                        key={key}
                        className={
                          "topic-matrix-cell" +
                          (mirror ? " mirror" : "") +
                          (internal ? " internal" : "") +
                          (sameFamily ? " same-family" : "")
                        }
                        aria-hidden={mirror || undefined}
                      >
                        {mirror ? (
                          <span className={relationClassName} style={relationStyle}>
                            {compactCount(relation.count)}
                          </span>
                        ) : (
                          <button
                            type="button"
                            className={relationClassName}
                            style={relationStyle}
                            aria-label={relationLabel}
                            aria-pressed={active}
                            onClick={() => setFocusedRelationKey(active ? null : key)}
                          >
                            {internal ? t("内·", "in·") : ""}{compactCount(relation.count)}
                          </button>
                        )}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="topic-association-legend">
        <span className="topic-association-heat">
          <i className="weak" /><i className="medium" /><i className="strong" />
          {t("主题对关联由弱到强", "topic-pair relation strength")}
        </span>
        <span className="topic-association-same">{t("同色区块 = 同一主题族", "same-color block = same topic family")}</span>
        <span>{t("展示当前折叠层全部聚合关系；对称呈现，不按条数裁剪", "all aggregates at the current collapsed level, shown symmetrically without count trimming")}</span>
      </div>
      <div className="topic-relation-detail">
        {selectedRelation ? (
          <>
            <strong>{selectedRelation.source === selectedRelation.target
              ? t(selectedRelation.source + " · 当前折叠范围内部", selectedRelation.source + " · within current collapsed scope")
              : selectedRelation.source + " ↔ " + selectedRelation.target}</strong>
            <span>{t(
              "主题对关联 " + selectedRelation.count + " · 聚合得分 " + selectedRelation.score.toFixed(1),
              selectedRelation.count + " topic-pair relations · aggregate score " + selectedRelation.score.toFixed(1)
            )}</span>
            <span className="topic-relation-reasons">{selectedRelation.reasons.join(" · ")}</span>
            <button type="button" onClick={() => onPick(selectedRelation.source)}>
              {t("查看 " + selectedRelation.source, "View " + selectedRelation.source)}
            </button>
            {selectedRelation.target !== selectedRelation.source ? (
              <button type="button" onClick={() => onPick(selectedRelation.target)}>
                {t("查看 " + selectedRelation.target, "View " + selectedRelation.target)}
              </button>
            ) : null}
          </>
        ) : selectedNode ? (
          <>
            <strong>{selectedNode.name}</strong>
            <span>{t(
              "上卷 " + selectedNode.count + " · 直挂 " + selectedNode.direct,
              selectedNode.count + " rolled up · " + selectedNode.direct + " direct"
            )}</span>
            {selectedChildCount ? (
              <button type="button" onClick={() => toggleChildren(selectedNode.name)}>
                {expandedParents.has(selectedNode.name)
                  ? t("收起子主题 (" + selectedChildCount + ")", "Collapse children (" + selectedChildCount + ")")
                  : t("展开子主题 (" + selectedChildCount + ")", "Expand children (" + selectedChildCount + ")")}
              </button>
            ) : null}
          </>
        ) : (
          <span>{t(
            "当前折叠层全部跨主题族关联都在矩阵中。点行首展开按钮或双击主题名，关联会同步下沉到具体子主题。",
            "Every cross-family relation at this collapsed level is shown. Use the row disclosure or double-click a topic name to move relations to specific children."
          )}</span>
        )}
      </div>
    </>
  );
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
      if (next.has(k)) next.delete(k);
      else next.add(k);
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
  const [viewMode, setViewMode] = useState<"topics" | "relations">("topics");

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
    return { nodes, edges };
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
      <div className="topic-view-switch" role="group" aria-label={t("图视角", "Graph view")}>
        <button type="button" aria-pressed={viewMode === "topics"} className={viewMode === "topics" ? "on" : ""} onClick={() => setViewMode("topics")}>{t("主题汇总", "Topic summary")}</button>
        <button type="button" aria-pressed={viewMode === "relations"} className={viewMode === "relations" ? "on" : ""} onClick={() => setViewMode("relations")}>{t("关联总览", "Relation overview")}</button>
      </div>
      {viewMode === "relations" ? (
        <RelationOverview selected={selected} onPick={pick} />
      ) : (
        <div id="tgraph">
        {loading ? (
          <div className="empty">{t("加载中…", "Loading…")}</div>
        ) : error ? (
          <div className="empty">{t("主题图加载失败，请稍后重试。", "The topic graph failed to load. Please try again later.")}</div>
        ) : !graph ? (
          <div className="empty">
            {t("还没有主题。同步记录并完成归类后，主题汇总会显示在这里。", "No topics yet. After syncing and classifying records, the topic summary appears here.")}
          </div>
        ) : (
          <TopicSummary
            nodes={graph.nodes}
            edges={graph.edges}
            selected={selected}
            onPick={pick}
          />
        )}
        </div>
      )}

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
          <div className="empty">{viewMode === "relations"
            ? t("↑ 点矩阵左侧主题,看这件事的全景(含子树上卷)", "↑ Click a topic row to see everything about it (subtree rolled up)")
            : t("↑ 点主题卡片,看这件事的全景(含子树上卷)", "↑ Click a topic card to see everything about it (subtree rolled up)")}</div>
        )}
      </div>
    </>
  );
}
