// Loom brand mark — the inline SVG woven-grid logo copied verbatim from
// browse.html (~line 508). Class names (loom-mark-board/weft/warp) are kept so
// the ported CSS (incl. the desktop recolor) applies unchanged.

export function BrandMark() {
  return (
    <svg viewBox="0 0 100 100" aria-hidden="true">
      <rect
        className="loom-mark-board"
        x="2"
        y="2"
        width="96"
        height="96"
        rx="22"
        fill="#141821"
        stroke="#2A313D"
      />
      <g className="loom-mark-weft" fill="#5AA9A0">
        <rect x="14" y="21.5" width="72" height="9" rx="4.5" />
        <rect x="14" y="45.5" width="72" height="9" rx="4.5" />
        <rect x="14" y="69.5" width="72" height="9" rx="4.5" />
      </g>
      <g className="loom-mark-warp" fill="#E0A84E">
        <rect x="21.5" y="14" width="9" height="72" rx="4.5" />
        <rect x="45.5" y="14" width="9" height="72" rx="4.5" />
        <rect x="69.5" y="14" width="9" height="72" rx="4.5" />
      </g>
      <g className="loom-mark-weft" fill="#5AA9A0">
        <rect x="45.5" y="21.5" width="9" height="9" rx="2.5" />
        <rect x="21.5" y="45.5" width="9" height="9" rx="2.5" />
        <rect x="69.5" y="45.5" width="9" height="9" rx="2.5" />
        <rect x="45.5" y="69.5" width="9" height="9" rx="2.5" />
      </g>
    </svg>
  );
}
