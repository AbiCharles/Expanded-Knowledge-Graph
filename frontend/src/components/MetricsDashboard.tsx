/**
 * Live metrics dashboard. Pulls /api/metrics/summary and renders four charts
 * + headline tiles. Charts are hand-rolled SVG — no dep, fits the design.
 */
import { useEffect, useState } from "react";
import * as api from "../api";

const PHASE_COLOR: Record<string, string> = {
  complete: "var(--emerald)",
  cancelled: "var(--ink-muted)",
  awaiting_clarification: "var(--cyan)",
  binding: "var(--cyan)",
  review_ready: "var(--amber)",
  reviewing: "var(--amber)",
};

const DECISION_COLOR: Record<string, string> = {
  approve: "var(--emerald)",
  reject: "var(--crimson)",
  request_more_info: "var(--amber)",
  auto_execute: "var(--cyan)",
  in_progress: "var(--ink-muted)",
};

export function MetricsDashboard({ onClose }: { onClose: () => void }) {
  const [data, setData] = useState<api.MetricsSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.getMetrics().then(setData).catch((e) => setError((e as Error).message));
  }, []);

  return (
    <div
      className="modal-backdrop"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="metrics-modal">
        <div className="ds-header">
          <div>
            <div className="ds-eyebrow">Metrics dashboard</div>
            <div className="ds-title">Case + decision insights</div>
          </div>
          <button className="teams-close" onClick={onClose}>×</button>
        </div>

        {error && <div className="ds-error">{error}</div>}
        {!data && !error && <div className="metrics-loading">Loading…</div>}

        {data && (
          <div className="metrics-body">
            <div className="metrics-scope">
              Scope: <code>{data.scope}</code>
            </div>

            <div className="metrics-tiles">
              <Tile label="Total cases" value={data.totals.all_cases} />
              <Tile label="Completed" value={data.totals.complete} accent="var(--emerald)" />
              <Tile label="In progress" value={data.totals.in_progress} accent="var(--amber)" />
            </div>

            <Section title="Cases by status">
              {data.cases_by_status.length === 0
                ? <Empty>No cases yet.</Empty>
                : <BarRow rows={data.cases_by_status.map((r) => ({
                    label: r.phase,
                    value: r.count,
                    color: PHASE_COLOR[r.phase] || "var(--cyan)",
                  }))} />}
            </Section>

            <Section title="Decisions by scenario">
              {data.decisions_by_scenario.length === 0
                ? <Empty>No decisions recorded yet.</Empty>
                : <DecisionStack data={data.decisions_by_scenario} />}
            </Section>

            <Section title="Cases per day · last 30 days">
              {data.cases_per_day.length === 0
                ? <Empty>No activity in the last 30 days.</Empty>
                : <Sparkline data={data.cases_per_day} />}
            </Section>

            <Section title="Top rejection reasons">
              {data.top_rejection_reasons.length === 0
                ? <Empty>No rejected cases yet.</Empty>
                : <ReasonList rows={data.top_rejection_reasons} />}
            </Section>
          </div>
        )}
      </div>
    </div>
  );
}

// =============================================================================
// Sub-components
// =============================================================================
function Tile({ label, value, accent }: { label: string; value: number; accent?: string }) {
  return (
    <div className="metrics-tile" style={accent ? { borderLeftColor: accent } : undefined}>
      <div className="metrics-tile-value">{value.toLocaleString()}</div>
      <div className="metrics-tile-label">{label}</div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="metrics-section">
      <div className="metrics-section-title">{title}</div>
      {children}
    </div>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return <div className="metrics-empty">{children}</div>;
}

function BarRow({ rows }: { rows: { label: string; value: number; color: string }[] }) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  return (
    <div className="metrics-bar-rows">
      {rows.map((r) => (
        <div key={r.label} className="metrics-bar-row">
          <div className="metrics-bar-label">{r.label}</div>
          <div className="metrics-bar-track">
            <div
              className="metrics-bar-fill"
              style={{ width: `${(r.value / max) * 100}%`, background: r.color }}
            />
          </div>
          <div className="metrics-bar-value">{r.value}</div>
        </div>
      ))}
    </div>
  );
}

function DecisionStack({
  data,
}: {
  data: { scenario_id: string; approve: number; reject: number; request_more_info: number; auto_execute: number; in_progress: number }[];
}) {
  const max = Math.max(1, ...data.map((r) => r.approve + r.reject + r.request_more_info + r.auto_execute + r.in_progress));
  const order: Array<keyof Omit<typeof data[0], "scenario_id">> = ["approve", "auto_execute", "request_more_info", "reject", "in_progress"];

  return (
    <div className="metrics-stack">
      {data.map((row) => {
        const total = order.reduce((s, k) => s + (row[k] as number), 0);
        return (
          <div key={row.scenario_id} className="metrics-stack-row">
            <div className="metrics-bar-label" title={row.scenario_id}>{row.scenario_id}</div>
            <div className="metrics-stack-track">
              {order.map((k) => {
                const v = row[k] as number;
                if (!v) return null;
                return (
                  <div
                    key={k}
                    className="metrics-stack-segment"
                    style={{
                      width: `${(v / max) * 100}%`,
                      background: DECISION_COLOR[k as string] || "var(--cyan)",
                    }}
                    title={`${k}: ${v}`}
                  >
                    {v >= max * 0.08 ? v : ""}
                  </div>
                );
              })}
            </div>
            <div className="metrics-bar-value">{total}</div>
          </div>
        );
      })}
      <div className="metrics-legend">
        {order.map((k) => (
          <span key={k}><span className="metrics-legend-swatch" style={{ background: DECISION_COLOR[k] }} /> {k}</span>
        ))}
      </div>
    </div>
  );
}

function Sparkline({ data }: { data: { date: string; count: number }[] }) {
  const W = 580;
  const H = 120;
  const PAD = 24;
  const max = Math.max(1, ...data.map((d) => d.count));
  const xStep = data.length > 1 ? (W - 2 * PAD) / (data.length - 1) : 0;
  const points = data
    .map((d, i) => `${PAD + i * xStep},${H - PAD - (d.count / max) * (H - 2 * PAD)}`)
    .join(" ");
  return (
    <svg className="metrics-sparkline" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none">
      <polyline
        fill="rgba(0,201,183,0.12)"
        stroke="none"
        points={`${PAD},${H - PAD} ${points} ${W - PAD},${H - PAD}`}
      />
      <polyline fill="none" stroke="var(--cyan)" strokeWidth="2" points={points} />
      {data.map((d, i) => {
        const x = PAD + i * xStep;
        const y = H - PAD - (d.count / max) * (H - 2 * PAD);
        return (
          <g key={d.date}>
            <circle cx={x} cy={y} r="2.5" fill="var(--navy-deep)" />
            <title>{d.date}: {d.count}</title>
          </g>
        );
      })}
      {/* axis line */}
      <line x1={PAD} y1={H - PAD} x2={W - PAD} y2={H - PAD} stroke="var(--rule)" strokeWidth="1" />
      {data.length > 0 && (
        <>
          <text x={PAD} y={H - 6} fontSize="9" fill="var(--ink-muted)" fontFamily="DM Mono">
            {data[0].date}
          </text>
          <text x={W - PAD} y={H - 6} fontSize="9" fill="var(--ink-muted)" fontFamily="DM Mono" textAnchor="end">
            {data[data.length - 1].date}
          </text>
        </>
      )}
    </svg>
  );
}

function ReasonList({ rows }: { rows: { reason: string; count: number }[] }) {
  return (
    <div className="metrics-reasons">
      {rows.map((r) => (
        <div key={r.reason} className="metrics-reason">
          <span className="metrics-reason-count">{r.count}×</span>
          <span className="metrics-reason-text">{r.reason}</span>
        </div>
      ))}
    </div>
  );
}
