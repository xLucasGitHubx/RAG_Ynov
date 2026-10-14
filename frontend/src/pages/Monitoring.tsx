import { ThumbsDown, ThumbsUp } from "@phosphor-icons/react";
import { useState } from "react";
import { Link } from "react-router";
import { BarList, LineChartBlock, SERIES } from "../components/charts";
import { ErrorState } from "../components/ErrorState";
import { DataTable } from "../components/tables";
import { Card, CardHeader, CodeLine, EmptyState, LoadingBlock, Mono, PageHeader, SegmentedControl, StatTile } from "../components/ui";
import type { Config, Monitoring } from "../lib/api";
import { STAGE_LABELS, fmt } from "../lib/format";
import { useApi } from "../lib/hooks";

const STATUS_LABELS: Record<string, string> = {
  ok: "Traitées",
  bloquee_rgpd: "Bloquées (RGPD)",
  erreur_llm: "Erreur du LLM",
};

export function MonitoringPage() {
  const [refresh, setRefresh] = useState<"on" | "off">("on");
  const data = useApi<Monitoring>("/api/monitoring", refresh === "on" ? 10000 : undefined);
  const config = useApi<Config>("/api/config");
  const m = data.data;
  const production = config.data?.environment === "production";

  return (
    <>
      <PageHeader
        title="Monitoring."
        description={
          <>
            Chaque question posée à l'API devient un run MLflow : durée de chaque étape, nombre d'extraits, scores,
            tokens, refus et feedback. Jamais le texte de la question.
            {production &&
              " Sur Azure, la base MLflow vit dans le conteneur : elle repart de zéro à chaque déploiement."}
          </>
        }
        action={
          <SegmentedControl
            label="Actualisation automatique"
            value={refresh}
            onChange={setRefresh}
            options={[
              { value: "on", label: "Actualiser toutes les 10 s" },
              { value: "off", label: "Pause" },
            ]}
          />
        }
      />
      {data.error ? (
        <ErrorState error={data.error} onRetry={data.reload} />
      ) : !m ? (
        <LoadingBlock />
      ) : !m.available ? (
        <EmptyState title="Suivi indisponible.">
          {m.reason} Activez <code>MLFLOW_TRACKING_ENABLED=true</code> : le client MLflow et sa base SQLite sont déjà dans
          les dépendances de l'API.
        </EmptyState>
      ) : !m.total ? (
        <EmptyState
          title="Aucune question suivie pour l'instant."
          action={
            <Link to="/assistant" className="text-sm font-medium text-accent-ink underline-offset-4 hover:underline">
              Poser une question à l'assistant
            </Link>
          }
        >
          Les mesures apparaissent ici dès la première question.
        </EmptyState>
      ) : (
        <MonitoringView m={m} />
      )}
    </>
  );
}

function MonitoringView({ m }: { m: Monitoring }) {
  const latency = m.latency ?? {};
  const recent = m.recent ?? [];
  const chronological = recent
    .filter((r) => r.status === "ok" && r.total_ms != null)
    .slice()
    .reverse()
    .map((r, i) => ({ n: String(i + 1), total: r.total_ms, llm: r.llm_ms }));
  const feedback = m.feedback ?? { positive: 0, negative: 0 };

  return (
    <div className="grid grid-cols-1 gap-4">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile label="Questions suivies" value={fmt.int(m.total)} detail={blockedLabel(m.statuses?.bloquee_rgpd ?? 0)} emphasis />
        <StatTile label="Latence médiane" value={fmt.ms(latency.total?.p50)} detail={`95e centile : ${fmt.ms(latency.total?.p95)}`} emphasis />
        <StatTile label="Taux de refus" value={fmt.pct(m.refusal_rate)} detail={`LLM appelé pour ${fmt.pct(m.llm_call_rate)} des questions`} emphasis />
        <StatTile
          label="Retours des utilisateurs"
          emphasis
          value={
            <span className="inline-flex items-center gap-4">
              <span className="inline-flex items-center gap-1.5">
                <ThumbsUp size={24} aria-label="Utiles" />
                {feedback.positive}
              </span>
              <span className="inline-flex items-center gap-1.5">
                <ThumbsDown size={24} aria-label="À améliorer" />
                {feedback.negative}
              </span>
            </span>
          }
          detail="Pouces reliés au run de la question"
        />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1.4fr_1fr]">
        <Card>
          <CardHeader title="Durée des dernières questions" description="Total et part de la génération, de la plus ancienne à la plus récente." />
          <div className="p-5">
            {chronological.length > 1 ? (
              <LineChartBlock
                ariaLabel="Durée totale et durée de génération par question"
                data={chronological}
                xKey="n"
                xLabel={(n) => `Question ${n}`}
                series={[
                  { key: "total", label: "Total", color: SERIES[0] },
                  { key: "llm", label: "Génération (LLM)", color: SERIES[1] },
                ]}
                yDomain={[0, Math.ceil(Math.max(...chronological.map((r) => r.total ?? 0)) / 5000) * 5000]}
                yFormat={(n) => fmt.ms(n)}
                height={220}
              />
            ) : (
              <p className="text-sm text-ink-3">Posez au moins deux questions pour voir l'évolution.</p>
            )}
          </div>
        </Card>
        <Card>
          <CardHeader title="Où passe le temps" description="Par étape, sur les questions traitées." />
          <div className="p-5">
            <DataTable
              caption="Latence par étape"
              head={["Étape", "Médiane", "95e centile", "Mesures"]}
              rows={["embedding", "vector_search", "lexical_search", "rerank", "llm", "total"]
                .filter((stage) => latency[stage])
                .map((stage) => [
                  STAGE_LABELS[stage],
                  fmt.ms(latency[stage].p50),
                  fmt.ms(latency[stage].p95),
                  fmt.int(latency[stage].count),
                ])}
            />
            <div className="mt-5">
              <BarList
                label="Répartition des questions par statut"
                max={m.total ?? 1}
                format={(n) => fmt.int(n)}
                rows={Object.entries(m.statuses ?? {}).map(([status, count]) => ({
                  key: status,
                  label: STATUS_LABELS[status] ?? status,
                  value: count,
                  highlight: status === "ok",
                }))}
              />
            </div>
          </div>
        </Card>
      </div>

      <Card>
        <CardHeader title="Dernières requêtes" description="Identifiant aléatoire, mesures et feedback : aucune donnée sur la personne ni sur le contenu." />
        <div className="mt-4 overflow-x-auto border-t border-line">
          <table className="w-full min-w-[720px] text-sm">
            <caption className="sr-only">Dernières requêtes suivies</caption>
            <thead>
              <tr className="bg-surface-2 text-left text-[13px] text-ink-3">
                {["Heure", "Requête", "Statut", "Sources", "Meilleur score", "Total", "LLM", "Retour"].map((h, i) => (
                  <th key={h} scope="col" className={`px-4 py-2.5 font-normal ${i >= 3 ? "text-right" : ""}`}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {recent.slice(0, 20).map((r) => (
                <tr key={r.request_id + r.time} className="border-t border-line">
                  <td className="px-4 py-2 tnum text-ink-2">{fmt.time(r.time)}</td>
                  <td className="px-4 py-2">
                    <Mono className="text-ink-2">{r.request_id}</Mono>
                  </td>
                  <td className="px-4 py-2 text-ink-2">
                    {r.status === "ok" ? (r.refused ? (r.llm_called ? "Refus du LLM" : "Refus sans LLM") : "Répondue") : STATUS_LABELS[r.status] ?? r.status}
                  </td>
                  <td className="px-4 py-2 text-right tnum text-ink-2">{r.n_sources ?? "—"}</td>
                  <td className="px-4 py-2 text-right tnum text-ink-2">{fmt.dec2(r.top_score)}</td>
                  <td className="px-4 py-2 text-right tnum text-ink">{fmt.ms(r.total_ms)}</td>
                  <td className="px-4 py-2 text-right tnum text-ink-2">{fmt.ms(r.llm_ms)}</td>
                  <td className="px-4 py-2 text-right">
                    {r.feedback == null ? (
                      <span className="text-ink-3">—</span>
                    ) : r.feedback > 0 ? (
                      <ThumbsUp size={16} weight="fill" aria-label="Utile" className="ml-auto text-good" />
                    ) : (
                      <ThumbsDown size={16} weight="fill" aria-label="À améliorer" className="ml-auto text-bad" />
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="grid grid-cols-1 gap-1.5 border-t border-line p-5">
          <p className="text-[13px] text-ink-2">Toutes les expériences (évaluations, requêtes) dans l'interface MLflow :</p>
          <CodeLine>mlflow ui --backend-store-uri sqlite:///mlflow.db</CodeLine>
        </div>
      </Card>
    </div>
  );
}

function blockedLabel(n: number): string {
  if (n === 0) return "Aucune bloquée par le filtre RGPD";
  return n === 1 ? "1 bloquée par le filtre RGPD" : `${n} bloquées par le filtre RGPD`;
}