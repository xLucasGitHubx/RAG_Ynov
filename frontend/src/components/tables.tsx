import type { ReactNode } from "react";
import { cx } from "./ui";

// Tableaux de données : la vue texte de chaque graphique (accessible, sans couleur seule).

export function TableView({ summary, children }: { summary: string; children: ReactNode }) {
  return (
    <details className="group border-t border-line">
      <summary className="cursor-pointer list-none px-5 py-3 text-[13px] font-medium text-ink-2 transition-colors duration-150 hover:text-ink [&::-webkit-details-marker]:hidden">
        <span className="group-open:hidden">{summary}</span>
        <span className="hidden group-open:inline">Masquer les valeurs</span>
      </summary>
      <div className="px-5 pb-5">{children}</div>
    </details>
  );
}

export function DataTable({
  caption,
  head,
  rows,
  highlightRow,
}: {
  caption: string;
  head: string[];
  rows: ReactNode[][];
  highlightRow?: number;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr className="text-left text-[13px] text-ink-3">
            {head.map((h, i) => (
              <th key={h} scope="col" className={cx("pb-2 font-normal whitespace-nowrap", i > 0 && "pl-4 text-right")}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, r) => (
            <tr key={r} className={cx("border-t border-line", r === highlightRow && "font-medium text-ink")}>
              {row.map((cell, i) =>
                i === 0 ? (
                  <th key={i} scope="row" className={cx("py-2 pr-2 text-left font-normal", r === highlightRow ? "font-medium text-ink" : "text-ink-2")}>
                    {cell}
                  </th>
                ) : (
                  <td key={i} className={cx("py-2 pl-4 text-right whitespace-nowrap tnum", r === highlightRow ? "text-ink" : "text-ink-2")}>
                    {cell}
                  </td>
                ),
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

