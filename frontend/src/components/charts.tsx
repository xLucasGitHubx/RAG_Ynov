import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Legend } from "./legend";
import { cx } from "./ui";

export { LatencyBreakdown, Legend } from "./legend";

// Couleurs par rôle (variables CSS des deux thèmes) : la couleur suit l'entité, jamais le rang.
export const SERIES = ["var(--series-1)", "var(--series-2)", "var(--series-3)"];

// ---------------------------------------------------------------- courbes (Recharts)

interface LineSeries {
  key: string;
  label: string;
  color: string;
}

export function LineChartBlock({
  data,
  xKey,
  series,
  yDomain,
  yFormat,
  xLabel,
  height = 240,
  ariaLabel,
}: {
  data: Record<string, number | string | null>[];
  xKey: string;
  series: LineSeries[];
  yDomain?: [number, number];
  yFormat: (n: number) => string;
  xLabel?: (value: string) => string;
  height?: number;
  ariaLabel: string;
}) {
  return (
    <figure aria-label={ariaLabel} className="m-0">
      {series.length > 1 && (
        <div className="mb-3">
          <Legend items={series.map((s) => ({ label: s.label, color: s.color }))} />
        </div>
      )}
      <div style={{ height }} className="tnum text-xs">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
            <CartesianGrid vertical={false} stroke="var(--grid)" />
            <XAxis
              dataKey={xKey}
              tickLine={false}
              axisLine={{ stroke: "var(--axis)" }}
              tick={{ fill: "var(--ink-3)", fontSize: 12 }}
              tickFormatter={xLabel}
              tickMargin={8}
            />
            <YAxis
              domain={yDomain ?? ["auto", "auto"]}
              tickLine={false}
              axisLine={false}
              tick={{ fill: "var(--ink-3)", fontSize: 12 }}
              tickFormatter={yFormat}
              width={52}
            />
            <Tooltip
              cursor={{ stroke: "var(--axis)", strokeWidth: 1 }}
              content={(props) => (
                <ChartTooltip
                  active={props.active}
                  payload={props.payload}
                  label={props.label}
                  series={series}
                  yFormat={yFormat}
                  xLabel={xLabel}
                />
              )}
            />
            {series.map((s) => (
              <Line
                key={s.key}
                dataKey={s.key}
                name={s.label}
                type="linear"
                stroke={s.color}
                strokeWidth={2}
                strokeLinecap="round"
                strokeLinejoin="round"
                dot={{ r: 4, fill: s.color, stroke: "var(--surface)", strokeWidth: 2 }}
                activeDot={{ r: 5, fill: s.color, stroke: "var(--surface)", strokeWidth: 2 }}
                isAnimationActive={false}
                connectNulls
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </figure>
  );
}

function ChartTooltip({
  active,
  payload,
  label,
  series,
  yFormat,
  xLabel,
}: {
  active?: boolean;
  payload?: readonly { dataKey?: unknown; value?: unknown }[];
  label?: unknown;
  series: LineSeries[];
  yFormat: (n: number) => string;
  xLabel?: (value: string) => string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="min-w-40 rounded-md bg-surface px-3 py-2 text-[13px] shadow-[var(--overlay-shadow)]">
      <p className="mb-1 font-medium text-ink">{xLabel ? xLabel(String(label)) : String(label)}</p>
      <ul className="grid grid-cols-1 gap-0.5">
        {payload.map((entry) => {
          const s = series.find((x) => x.key === entry.dataKey);
          if (!s || entry.value == null) return null;
          return (
            <li key={s.key} className="flex items-center justify-between gap-4 text-ink-2">
              <span className="flex items-center gap-2">
                <span aria-hidden="true" className="h-2 w-3 rounded-[2px]" style={{ background: s.color }} />
                {s.label}
              </span>
              <span className="tnum font-medium text-ink">{yFormat(Number(entry.value))}</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

// ---------------------------------------------------------------- barres horizontales

/**
 * Barres horizontales à une série : la configuration retenue est mise en avant (accent),
 * les autres restent grises. La valeur est écrite au bout de chaque barre (pas de tooltip
 * nécessaire : le graphique se lit aussi comme un tableau).
 */
export function BarList({
  rows,
  format,
  max = 1,
  label,
}: {
  rows: { label: ReactNode; value: number; highlight?: boolean; detail?: ReactNode; key: string }[];
  format: (n: number) => string;
  max?: number;
  label: string;
}) {
  return (
    <ul aria-label={label} className="grid grid-cols-1 gap-3">
      {rows.map((row) => (
        <li key={row.key} className="grid grid-cols-1 gap-1.5">
          <div className="flex items-baseline justify-between gap-3 text-sm">
            <span className={cx("min-w-0 truncate", row.highlight ? "font-medium text-ink" : "text-ink-2")}>{row.label}</span>
            <span className="tnum shrink-0 font-medium text-ink">{format(row.value)}</span>
          </div>
          <div className="h-2 rounded-full bg-surface-2">
            <div
              className="h-full rounded-full"
              style={{
                width: `${Math.max(0, Math.min(1, row.value / max)) * 100}%`,
                background: row.highlight ? "var(--series-1)" : "var(--series-muted)",
              }}
            />
          </div>
          {row.detail && <p className="text-xs text-ink-3">{row.detail}</p>}
        </li>
      ))}
    </ul>
  );
}

// ---------------------------------------------------------------- nuage de points 1D (seuil)

export interface StripPoint {
  id: string;
  value: number;
  group: string;
}

/**
 * Score de chaque question sur un axe, une ligne par groupe, avec le seuil de refus.
 * Survol ou focus clavier : identifiant et score de la question.
 */
export function StripPlot({
  points,
  groups,
  threshold,
  domain,
  format,
  ariaLabel,
}: {
  points: StripPoint[];
  groups: { id: string; label: string; color: string }[];
  threshold: number;
  domain: [number, number];
  format: (n: number) => string;
  ariaLabel: string;
}) {
  const [hover, setHover] = useState<StripPoint | null>(null);
  const clipId = useId();
  const [frameRef, width] = useElementWidth<HTMLDivElement>();
  // Dessiné à la largeur réelle du conteneur : le texte garde sa taille (pas de mise à l'échelle).
  const rowHeight = 64;
  const left = 18; // place pour le premier libellé d'axe, centré sur sa graduation
  const right = 18;
  const top = 34;
  const height = top + groups.length * rowHeight + 28;
  const plotWidth = Math.max(0, width - left - right);
  const x = (v: number) => left + ((v - domain[0]) / (domain[1] - domain[0])) * plotWidth;
  const ticks = useMemo(() => {
    const out = [];
    const step = width < 420 ? 0.2 : 0.1;
    for (let v = Math.ceil(domain[0] * 10) / 10; v <= domain[1] + 1e-9; v += step) out.push(Number(v.toFixed(2)));
    return out;
  }, [domain, width]);

  // Petits décalages verticaux déterministes pour que les points proches restent visibles.
  const jitter = (id: string) => {
    let h = 0;
    for (const c of id) h = (h * 31 + c.charCodeAt(0)) % 997;
    return ((h % 7) - 3) * 3.4;
  };
  const thresholdRight = x(threshold) > width * 0.6;

  return (
    <figure className="m-0">
      <div ref={frameRef} className="relative">
        {width > 0 && (
          <svg width={width} height={height} role="img" aria-label={ariaLabel} className="block">
            <defs>
              <clipPath id={clipId}>
                <rect x={0} y={0} width={width} height={height} />
              </clipPath>
            </defs>
            {ticks.map((t) => (
              <g key={t}>
                <line x1={x(t)} x2={x(t)} y1={top - 6} y2={height - 24} stroke="var(--grid)" strokeWidth={1} />
                <text x={x(t)} y={height - 6} textAnchor="middle" fontSize={12} fill="var(--ink-3)" className="tnum">
                  {format(t)}
                </text>
              </g>
            ))}
            <line x1={x(threshold)} x2={x(threshold)} y1={top - 14} y2={height - 24} stroke="var(--ink)" strokeWidth={1.5} />
            <text
              x={x(threshold) + (thresholdRight ? -6 : 6)}
              y={top - 18}
              textAnchor={thresholdRight ? "end" : "start"}
              fontSize={12}
              fill="var(--ink)"
              fontWeight={500}
            >
              Seuil {format(threshold)} · refus sans LLM à gauche
            </text>
            {groups.map((g, row) => {
              const cy = top + row * rowHeight + rowHeight / 2 + 6;
              return (
                <g key={g.id}>
                  <text x={0} y={top + row * rowHeight + 12} fontSize={12} fill="var(--ink-2)">
                    {g.label}
                  </text>
                  <g clipPath={`url(#${clipId})`}>
                    {points
                      .filter((p) => p.group === g.id)
                      .map((p) => (
                        <circle
                          key={p.id}
                          cx={x(p.value)}
                          cy={cy + jitter(p.id)}
                          r={hover?.id === p.id ? 6.5 : 4.5}
                          fill={g.color}
                          stroke={hover?.id === p.id ? "var(--ink)" : "var(--surface)"}
                          strokeWidth={2}
                          tabIndex={0}
                          aria-label={`${p.id} : ${format(p.value)}`}
                          onMouseEnter={() => setHover(p)}
                          onMouseLeave={() => setHover(null)}
                          onFocus={() => setHover(p)}
                          onBlur={() => setHover(null)}
                          style={{ cursor: "default", outline: "none" }}
                        />
                      ))}
                  </g>
                </g>
              );
            })}
          </svg>
        )}
        {hover && width > 0 && (
          <div
            className="pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-full rounded-md bg-surface px-2.5 py-1.5 text-[13px] whitespace-nowrap shadow-[var(--overlay-shadow)]"
            style={{
              left: Math.min(Math.max(x(hover.value), 60), width - 60),
              top: top + groups.findIndex((g) => g.id === hover.group) * rowHeight + 18,
            }}
          >
            <span className="font-mono text-[12px] text-ink-2" translate="no">
              {hover.id}
            </span>{" "}
            <span className="tnum font-medium text-ink">{format(hover.value)}</span>
          </div>
        )}
      </div>
      <figcaption className="mt-3">
        <Legend items={groups.map((g) => ({ label: g.label, color: g.color }))} />
      </figcaption>
    </figure>
  );
}

/** Largeur d'un élément, suivie avec ResizeObserver (pas de lecture de mise en page au rendu). */
function useElementWidth<T extends HTMLElement>(): [React.RefObject<T | null>, number] {
  const ref = useRef<T | null>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.floor(entry.contentRect.width)));
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  return [ref, width];
}
