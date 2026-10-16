"use client";

import { useRouter } from "next/navigation";

type Node = { id: string; title: string; language: string; origin: string; sim_day: number | null; compliance_status: string };
type Edge = { id: string; source: string; target: string; direction: string; score: number; anchor_text: string };

const COLS = ["Inventory", "Day 1", "Day 2", "Day 3"];
const LANG_COLOR: Record<string, string> = { en: "#64748b", hi: "#d97706", "hi-Latn": "#6366f1" };

/** Day-columned internal-link graph: shows newer pages linking back to earlier, relevant pages. */
export function LinkGraph({ nodes, edges }: { nodes: Node[]; edges: Edge[] }) {
  const router = useRouter();
  const W = 1000, colW = W / COLS.length, rowH = 64, top = 40;
  const col = (n: Node) => (n.origin === "INVENTORY" ? 0 : Math.min(3, n.sim_day ?? 1));
  const byCol: Record<number, Node[]> = {};
  nodes.forEach((n) => (byCol[col(n)] ??= []).push(n));
  const pos = new Map<string, { x: number; y: number }>();
  Object.entries(byCol).forEach(([c, list]) => list.forEach((n, i) => pos.set(n.id, { x: Number(c) * colW + colW / 2, y: top + 30 + i * rowH })));
  const H = top + 60 + Math.max(...Object.values(byCol).map((l) => l.length), 1) * rowH;
  const shown = edges.filter((e) => e.direction !== "REVERSE_SUGGESTED" && pos.has(e.source) && pos.has(e.target));

  return (
    <div className="scrollbar-thin overflow-x-auto">
      <svg viewBox={`0 0 ${W} ${H}`} className="min-w-[760px]" role="img" aria-label="Internal link graph">
        <defs>
          <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
            <path d="M0,0 L10,5 L0,10 z" fill="#818cf8" />
          </marker>
        </defs>
        {COLS.map((c, i) => (
          <g key={c}>
            <rect x={i * colW + 8} y={8} width={colW - 16} height={H - 16} rx={10} fill={i === 0 ? "#f8fafc" : "#fafaff"} stroke="#eef2f7" />
            <text x={i * colW + colW / 2} y={30} textAnchor="middle" className="fill-slate-500 text-[12px] font-semibold">{c}</text>
          </g>
        ))}
        {shown.map((e) => {
          const s = pos.get(e.source)!, t = pos.get(e.target)!;
          const sx = s.x - 95, tx = t.x + 95;
          const mx = (sx + tx) / 2;
          return (
            <path key={e.id} d={`M${sx},${s.y} C${mx},${s.y} ${mx},${t.y} ${tx},${t.y}`} fill="none"
              stroke={e.direction === "INSERTED" ? "#818cf8" : "#cbd5e1"} strokeWidth={e.direction === "INSERTED" ? 1.6 : 1}
              strokeDasharray={e.direction === "INSERTED" ? undefined : "4 3"} markerEnd="url(#arrow)" opacity={0.85}>
              <title>{`${e.anchor_text} (${e.direction}, score ${e.score})`}</title>
            </path>
          );
        })}
        {nodes.map((n) => {
          const p = pos.get(n.id)!;
          const label = n.title.length > 30 ? n.title.slice(0, 29) + "…" : n.title;
          return (
            <g key={n.id} transform={`translate(${p.x - 95},${p.y - 20})`} className="cursor-pointer" onClick={() => router.push(`/content/${n.id}`)}>
              <rect width={190} height={40} rx={8} fill="white" stroke={n.compliance_status === "BLOCK" ? "#fda4af" : "#e2e8f0"} />
              <rect width={4} height={40} rx={2} fill={LANG_COLOR[n.language] ?? "#94a3b8"} />
              <text x={12} y={17} className="fill-slate-800 text-[11px] font-medium">{label}</text>
              <text x={12} y={31} className="fill-slate-400 text-[10px]">{n.language} · {n.origin === "INVENTORY" ? "existing page" : n.compliance_status}</text>
            </g>
          );
        })}
      </svg>
      <div className="mt-2 flex flex-wrap gap-4 px-1 text-xs text-slate-500">
        <span><span className="mr-1 inline-block h-0.5 w-5 bg-indigo-400 align-middle" />contextual in-body link</span>
        <span><span className="mr-1 inline-block h-0.5 w-5 border-t border-dashed border-slate-400 align-middle" />related-guides module</span>
        <span>colour bar: <b style={{ color: LANG_COLOR.en }}>EN</b> · <b style={{ color: LANG_COLOR.hi }}>HI</b> · <b style={{ color: LANG_COLOR["hi-Latn"] }}>Hinglish</b></span>
      </div>
    </div>
  );
}
