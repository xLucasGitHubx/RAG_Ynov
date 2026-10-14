import type { ReactNode } from "react";

// Légende et barre de latence : sans dépendance à Recharts (chargées par la page Assistant).

export function Legend({ items }: { items: { label: string; color: string; value?: ReactNode }[] }) {
  return (
    <ul className="flex flex-wrap gap-x-5 gap-y-1.5 text-[13px] text-ink-2">
      {items.map((item) => (
        <li key={item.label} className="flex items-center gap-2">
          <span aria-hidden="true" className="h-2 w-3 rounded-[2px]" style={{ background: item.color }} />
          <span>{item.label}</span>
          {item.value != null && <span className="tnum font-medium text-ink">{item.value}</span>}
        </li>
      ))}
    </ul>
  );
}

// ---------------------------------------------------------------- latence d'une réponse

/** Barre empilée « recherche / génération » (2 séries, écart de 2 px), légende chiffrée. */
export function LatencyBreakdown({ timings }: { timings: Record<string, number> }) {
  const retrieval = (timings.embedding ?? 0) + (timings.vector_search ?? 0) + (timings.lexical_search ?? 0) + (timings.rerank ?? 0);
  const llm = timings.llm ?? 0;
  const total = timings.total ?? retrieval + llm;
  const parts = [
    { label: "Recherche", value: retrieval, color: "var(--series-1)" },
    { label: "Génération", value: llm, color: "var(--series-2)" },
  ].filter((p) => p.value > 0);
  const sum = parts.reduce((acc, p) => acc + p.value, 0) || 1;
  return (
    <div className="grid grid-cols-1 gap-2">
      <div className="flex h-1.5 gap-0.5 overflow-hidden rounded-full" aria-hidden="true">
        {parts.map((p) => (
          <div
            key={p.label}
            className="h-full first:rounded-l-full last:rounded-r-full"
            style={{ width: `${Math.max(2, (p.value / sum) * 100)}%`, background: p.color }}
          />
        ))}
      </div>
      <Legend
        items={[
          ...parts.map((p) => ({ label: p.label, color: p.color, value: formatMs(p.value) })),
          { label: "Total", color: "transparent", value: formatMs(total) },
        ]}
      />
    </div>
  );
}

function formatMs(n: number): string {
  return n < 1000 ? `${Math.round(n)} ms` : `${(n / 1000).toLocaleString("fr-FR", { maximumFractionDigits: 1 })} s`;
}

