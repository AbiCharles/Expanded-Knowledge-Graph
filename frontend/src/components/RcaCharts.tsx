// Native visualizations for the RCA analysis methods, rendered from the
// structured synthesis output (/api/rca/analysis). Hand-rolled SVG/CSS so we
// don't pull in a charting lib. Used by the method tabs on the evidence-graph
// modal (see GraphViz.tsx).
import {
  RcaAnalysis,
  RcaEvidenceDoc,
  RcaFiveWhy,
  RcaIshikawa,
  RcaPareto,
} from "../api";

// =============================================================================
// Documents panel — the bound evidence "records" behind an analysis.
// =============================================================================
export function DocumentsPanel({
  docs,
  heading = "Supporting documents",
}: {
  docs: RcaEvidenceDoc[];
  heading?: string;
}) {
  return (
    <aside className="rca-docs">
      <div className="rca-docs-head">
        {heading}
        <span className="rca-docs-count">{docs.length}</span>
      </div>
      <div className="rca-docs-list">
        {docs.length === 0 && (
          <div className="rca-docs-empty">No bound documents for this view.</div>
        )}
        {docs.map((d) => {
          const kind = (d.source || "").split(":")[0];
          return (
            <div key={`${d.source}-${d.id}`} className="rca-doc">
              <div className="rca-doc-top">
                <span className="rca-doc-id">{d.id}</span>
                <span className={`rca-doc-kind rca-doc-kind-${kind}`}>{kind || "fact"}</span>
              </div>
              <div className="rca-doc-title">{d.title || d.id}</div>
              {d.summary && <div className="rca-doc-summary">{d.summary}</div>}
            </div>
          );
        })}
      </div>
    </aside>
  );
}

// =============================================================================
// Pareto — horizontal bars, ranked, with the vital-few (≈80%) callout.
// =============================================================================
export function ParetoChart({ data }: { data: RcaPareto }) {
  const pairs = data.pareto_items.map((item, i) => ({
    item,
    pct: data.pareto_percent[i] ?? 0,
  }));
  pairs.sort((a, b) => b.pct - a.pct);

  // Cumulative % (bars already sum to ~100, so the running sum is the curve).
  let running = 0;
  const rows = pairs.map((p) => {
    running += p.pct;
    return { ...p, cum: running };
  });
  const vitalCount = Math.max(1, rows.findIndex((r) => r.cum >= 80) + 1 || rows.length);
  const vital = rows.slice(0, vitalCount).map((r) => r.item);

  // SVG geometry — classic Pareto: descending bars (left axis) + cumulative
  // line (right axis, 0-100%) + an 80% reference rule.
  const W = 660;
  const H = 340;
  const m = { top: 20, right: 46, bottom: 78, left: 44 };
  const plotW = W - m.left - m.right;
  const plotH = H - m.top - m.bottom;
  const n = rows.length || 1;
  const slot = plotW / n;
  const bw = Math.min(64, slot * 0.6);
  const yMax = 100;
  const y = (v: number) => m.top + plotH - (v / yMax) * plotH;
  const barX = (i: number) => m.left + slot * i + (slot - bw) / 2;
  const cx = (i: number) => m.left + slot * i + slot / 2;
  const ticks = [0, 20, 40, 60, 80, 100];
  const linePts = rows.map((r, i) => `${cx(i)},${y(r.cum)}`).join(" ");

  return (
    <div className="rca-chart rca-pareto">
      <div className="rca-chart-title">Pareto — probable causes (bars) + cumulative % (line)</div>
      <div className="rca-pareto-scroll">
        <svg viewBox={`0 0 ${W} ${H}`} className="rca-pareto-svg" role="img">
          {/* gridlines + left axis ticks */}
          {ticks.map((t) => (
            <g key={t}>
              <line x1={m.left} y1={y(t)} x2={m.left + plotW} y2={y(t)} className="pc-grid" />
              <text x={m.left - 8} y={y(t) + 3} className="pc-axis-y" textAnchor="end">{t}</text>
              <text x={m.left + plotW + 8} y={y(t) + 3} className="pc-axis-y2" textAnchor="start">{t}%</text>
            </g>
          ))}
          {/* 80% reference rule */}
          <line x1={m.left} y1={y(80)} x2={m.left + plotW} y2={y(80)} className="pc-rule-80" />
          <text x={m.left + plotW} y={y(80) - 5} className="pc-rule-80-label" textAnchor="end">80%</text>
          {/* bars */}
          {rows.map((r, i) => (
            <g key={r.item}>
              <rect
                x={barX(i)} y={y(r.pct)} width={bw} height={m.top + plotH - y(r.pct)}
                className={`pc-bar${i === 0 ? " lead" : ""}`}
              />
              <text x={cx(i)} y={y(r.pct) - 5} className="pc-bar-val" textAnchor="middle">{r.pct}%</text>
              <text
                x={cx(i)} y={m.top + plotH + 16}
                className="pc-xlabel" textAnchor="end"
                transform={`rotate(-28 ${cx(i)} ${m.top + plotH + 16})`}
              >
                {truncate(r.item, 22)}
              </text>
            </g>
          ))}
          {/* cumulative line */}
          <polyline points={linePts} className="pc-cum-line" />
          {rows.map((r, i) => (
            <g key={`pt-${i}`}>
              <circle cx={cx(i)} cy={y(r.cum)} r={3.5} className="pc-cum-dot" />
              <text x={cx(i)} y={y(r.cum) - 8} className="pc-cum-val" textAnchor="middle">
                {Math.round(r.cum)}%
              </text>
            </g>
          ))}
          {/* axes */}
          <line x1={m.left} y1={m.top} x2={m.left} y2={m.top + plotH} className="pc-axis" />
          <line x1={m.left} y1={m.top + plotH} x2={m.left + plotW} y2={m.top + plotH} className="pc-axis" />
          <line x1={m.left + plotW} y1={m.top} x2={m.left + plotW} y2={m.top + plotH} className="pc-axis" />
        </svg>
      </div>
      <div className="rca-pareto-vital">
        <strong>Vital few (≈80%):</strong> {vital.join(" · ")}
      </div>
    </div>
  );
}

// =============================================================================
// Ishikawa — fishbone SVG: spine → effect, six category branches.
// =============================================================================
const FISH_CATS: { key: keyof RcaIshikawa; label: string; side: "top" | "bottom"; slot: number }[] = [
  { key: "machines", label: "Machines", side: "top", slot: 0 },
  { key: "methods", label: "Methods", side: "top", slot: 1 },
  { key: "materials", label: "Materials", side: "top", slot: 2 },
  { key: "measurement", label: "Measurement", side: "bottom", slot: 0 },
  { key: "people", label: "People", side: "bottom", slot: 1 },
  { key: "environment", label: "Environment", side: "bottom", slot: 2 },
];

export function FishboneDiagram({
  data,
  effect,
}: {
  data: RcaIshikawa;
  effect: string;
}) {
  const W = 920;
  const H = 460;
  const spineY = H / 2;
  const headX = W - 150;
  const slotX = [235, 445, 655]; // where each branch meets the spine
  return (
    <div className="rca-chart rca-fishbone">
      <div className="rca-chart-title">Ishikawa (fishbone) — cause categories</div>
      <div className="rca-fishbone-scroll">
        <svg viewBox={`0 0 ${W} ${H}`} className="rca-fishbone-svg" role="img">
          {/* Spine */}
          <line x1={24} y1={spineY} x2={headX} y2={spineY} className="fb-spine" />
          <polygon
            points={`${headX - 8},${spineY - 8} ${headX},${spineY} ${headX - 8},${spineY + 8}`}
            className="fb-spine-tip"
          />
          {/* Effect (defect) head */}
          <rect x={headX} y={spineY - 34} width={132} height={68} rx={8} className="fb-head" />
          <text x={headX + 66} y={spineY - 6} className="fb-head-label" textAnchor="middle">
            EFFECT
          </text>
          <text x={headX + 66} y={spineY + 14} className="fb-head-text" textAnchor="middle">
            {truncate(effect, 18)}
          </text>
          {FISH_CATS.map((c) => {
            const bx = slotX[c.slot];
            const top = c.side === "top";
            const endX = bx - 120;
            const endY = top ? spineY - 150 : spineY + 150;
            const causes = (data[c.key] as string[]) || [];
            return (
              <g key={c.key} className={`fb-branch fb-${c.side}`}>
                <line x1={bx} y1={spineY} x2={endX} y2={endY} className="fb-rib" />
                <rect
                  x={endX - 54}
                  y={top ? endY - 20 : endY}
                  width={108}
                  height={20}
                  rx={4}
                  className="fb-cat-box"
                />
                <text
                  x={endX}
                  y={top ? endY - 6 : endY + 14}
                  className="fb-cat-label"
                  textAnchor="middle"
                >
                  {c.label}
                </text>
                {causes.slice(0, 3).map((cause, i) => {
                  const cy = top ? endY + 16 + i * 15 : endY - 26 - i * 15;
                  return (
                    <text key={i} x={endX + 60} y={cy} className="fb-cause" textAnchor="start">
                      • {truncate(cause, 30)}
                    </text>
                  );
                })}
                {causes.length > 3 && (
                  <text
                    x={endX + 60}
                    y={top ? endY + 16 + 3 * 15 : endY - 26 - 3 * 15}
                    className="fb-cause fb-cause-more"
                    textAnchor="start"
                  >
                    +{causes.length - 3} more
                  </text>
                )}
                {causes.length === 0 && (
                  <text x={endX + 60} y={top ? endY + 16 : endY - 26} className="fb-cause fb-cause-none">
                    (none)
                  </text>
                )}
              </g>
            );
          })}
        </svg>
      </div>
      {data.primary_root_cause && (
        <div className="rca-fishbone-primary">
          <strong>Primary cause ({data.confidence}):</strong> {data.primary_root_cause}
        </div>
      )}
    </div>
  );
}

// =============================================================================
// 5-Why — a chain of numbered steps leading to the root cause.
// =============================================================================
export function FiveWhyChain({ data }: { data: RcaFiveWhy }) {
  return (
    <div className="rca-chart rca-5why">
      <div className="rca-chart-title">5-Why — causation chain</div>
      <div className="rca-5why-chain">
        {data.why_chain.map((s, i) => (
          <div key={i} className="rca-5why-node-wrap">
            <div className="rca-5why-node">
              <div className="rca-5why-num">Why {i + 1}</div>
              <div className="rca-5why-q">{s.question}</div>
              <div className="rca-5why-a">{s.answer}</div>
              {s.evidence && <div className="rca-5why-ev">evidence: {s.evidence}</div>}
            </div>
            <div className="rca-5why-arrow" aria-hidden="true">↓</div>
          </div>
        ))}
        <div className="rca-5why-root">
          <div className="rca-5why-root-label">Root cause · {data.confidence} confidence</div>
          <div className="rca-5why-root-text">{data.root_cause}</div>
        </div>
      </div>
      {data.recommended_actions.length > 0 && (
        <div className="rca-5why-actions">
          <div className="rca-5why-actions-label">Recommended actions</div>
          <ul>
            {data.recommended_actions.map((a, i) => (
              <li key={i}>{a}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

// =============================================================================
// Visual finding — the C-scan. No live vision service here, so we render a
// stylized scan placeholder with the defect region called out + the finding.
// =============================================================================
export function VisualFinding({ analysis }: { analysis: RcaAnalysis }) {
  const vision = analysis.vision;
  const hasImage = !!vision?.image_url;
  const visualNode = analysis.evidence_graph.nodes.find((n) => n.node_type === "visual");
  const finding =
    vision?.observations || visualNode?.description || "C-scan visual finding";
  const conf = visualNode?.confidence_score;

  return (
    <div className="rca-chart rca-visual">
      <div className="rca-chart-title">Visual finding — C-scan (defect image)</div>
      <div className="rca-visual-body">
        <div className="rca-visual-scan">
          {hasImage ? (
            <img
              className="rca-visual-img"
              src={vision!.image_url as string}
              alt={`C-scan for ${analysis.part_id}`}
            />
          ) : (
            <svg viewBox="0 0 320 220" className="rca-visual-svg" role="img">
              <rect x={0} y={0} width={320} height={220} className="vs-bg" />
              {Array.from({ length: 8 }).map((_, i) => (
                <line key={`v${i}`} x1={(i + 1) * 40} y1={0} x2={(i + 1) * 40} y2={220} className="vs-grid" />
              ))}
              {Array.from({ length: 5 }).map((_, i) => (
                <line key={`h${i}`} x1={0} y1={(i + 1) * 40} x2={320} y2={(i + 1) * 40} className="vs-grid" />
              ))}
              <ellipse cx={200} cy={120} rx={52} ry={26} className="vs-defect" />
              <ellipse cx={200} cy={120} rx={30} ry={14} className="vs-defect-core" />
              <text x={200} y={168} className="vs-defect-label" textAnchor="middle">delamination</text>
            </svg>
          )}
          <div className="rca-visual-caption">
            {hasImage
              ? "Live C-scan from the RCA vision service."
              : "Placeholder rendering — the external vision service is unavailable."}
          </div>
        </div>
        <div className="rca-visual-detail">
          {vision?.defect_type && (
            <>
              <div className="rca-visual-detail-label">Classification</div>
              <div className="rca-visual-detail-text">
                {vision.defect_type}
                {vision.severity ? ` · ${vision.severity} severity` : ""}
              </div>
            </>
          )}
          {vision?.location && (
            <>
              <div className="rca-visual-detail-label">Location</div>
              <div className="rca-visual-detail-text">{vision.location}</div>
            </>
          )}
          <div className="rca-visual-detail-label">Finding</div>
          <div className="rca-visual-detail-text">{finding}</div>
          {vision?.candidate_causes && (
            <>
              <div className="rca-visual-detail-label">Candidate causes (from image)</div>
              <div className="rca-visual-detail-text">{vision.candidate_causes}</div>
            </>
          )}
          {typeof conf === "number" && (
            <div className="rca-visual-conf">graph confidence {conf}%</div>
          )}
          <div className="rca-visual-detail-label">Part</div>
          <div className="rca-visual-detail-text">
            {analysis.part_id} · {analysis.defect_type}
          </div>
        </div>
      </div>
    </div>
  );
}

function truncate(s: string, n: number): string {
  if (!s) return "";
  return s.length <= n ? s : s.slice(0, n - 1) + "…";
}
