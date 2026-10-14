import { ArrowRight, CheckCircle, Circle, CircleHalf } from "@phosphor-icons/react";
import { Link } from "react-router";
import { ErrorState } from "../components/ErrorState";
import { Pipeline } from "../components/Pipeline";
import { Card, CardHeader, LoadingBlock, Mono, PageHeader, SectionTitle, StatTile } from "../components/ui";
import type { Config, Report } from "../lib/api";
import { fmt } from "../lib/format";
import { useApi } from "../lib/hooks";

const ROADMAP: { n: number; title: string; state: "done" | "partial" | "todo"; detail: string }[] = [
  { n: 1, title: "Squelette", state: "done", detail: "API FastAPI, /ask, Swagger" },
  { n: 2, title: "Conteneurisation", state: "done", detail: "Dockerfile multi-stage, utilisateur non root" },
  { n: 3, title: "Mémoire", state: "done", detail: "Docling, découpage mesuré, BGE-M3, ChromaDB" },
  { n: 4, title: "Cerveau", state: "done", detail: "Ollama local, Space ZeroGPU (8B), recherche hybride, streaming" },
  { n: 5, title: "Déploiement cloud", state: "done", detail: "Azure Container Apps et Space ZeroGPU, mise en ligne par GitHub Actions" },
  { n: 6, title: "Optimisation", state: "done", detail: "Rerankers et quantization (GGUF, int8, nf4) mesurés" },
  { n: 7, title: "Sécurité et RGPD", state: "done", detail: "Filtre de données personnelles, clés, limite de débit" },
  { n: 8, title: "MLOps", state: "done", detail: "MLflow : évaluations, requêtes en production, feedback, registre" },
  { n: 9, title: "FinOps et documentation", state: "done", detail: "Budget au temps GPU mesuré, documentation et page « Le projet »" },
];

const STATE = {
  done: { icon: CheckCircle, label: "Fait", className: "text-good" },
  partial: { icon: CircleHalf, label: "En partie", className: "text-warn" },
  todo: { icon: Circle, label: "À faire", className: "text-ink-3" },
};

export function OverviewPage() {
  const report = useApi<Report>("/api/reports");
  const config = useApi<Config>("/api/config");

  const runs = report.data?.answers.runs ?? [];
  const v3 = runs.find((r) => r.version === "zerogpu") ?? runs.find((r) => r.version === "v3") ?? runs.at(-1);
  const production = v3?.version === "zerogpu";
  const hybrid = report.data?.retrieval.comparison.find((c) => c.key === "hybrid");
  const tests = report.data?.tests;
  const security = report.data?.security;

  return (
    <>
      <PageHeader
        title="Assistant RH et IT de Nexalis Conseil."
        description="Les salariés posent leurs questions sur les congés, le télétravail, la mutuelle ou le VPN. L'assistant répond uniquement à partir des documents internes, cite ses sources et refuse ce qui sort de son périmètre."
        action={
          <div className="flex flex-wrap gap-2">
            <Link
              to="/projet"
              className="inline-flex h-10 items-center rounded-md bg-surface px-4 text-sm font-medium text-ink shadow-[inset_0_0_0_1px_var(--line-strong)] transition-[background-color,transform] duration-150 hover:bg-surface-2 active:scale-[0.98]"
            >
              Comprendre le projet
            </Link>
            <Link
              to="/assistant"
              className="inline-flex h-10 items-center gap-2 rounded-md bg-ink px-4 text-sm font-medium text-bg transition-[background-color,transform] duration-150 hover:bg-ink/85 active:scale-[0.98]"
            >
              Poser une question
              <ArrowRight size={16} aria-hidden="true" />
            </Link>
          </div>
        }
      />

      {report.error ? (
        <ErrorState error={report.error} onRetry={report.reload} />
      ) : !report.data ? (
        <LoadingBlock />
      ) : (
        <>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-[1.4fr_1fr_1fr]">
            <div className="sm:col-span-2 lg:col-span-1 lg:row-span-2">
              <Card as="div" className="flex h-full flex-col justify-between gap-6 p-6">
                <div>
                  <p className="text-[13px] text-ink-3">Réponses correctes, de bout en bout</p>
                  <p className="mt-2 text-[56px] leading-[56px] font-semibold tracking-[-2.6px] text-ink">
                    {fmt.pct(v3?.summary.accuracy)}
                  </p>
                  <p className="mt-3 max-w-[42ch] text-sm text-ink-2">
                    {v3?.summary.correct} questions sur {v3?.summary.evaluated}, avec chiffres et termes attendus, par{" "}
                    {production ? (
                      <>Ministral 3 8B en bf16 sur ZeroGPU.</>
                    ) : (
                      <>
                        <Mono>{report.data.retained.llm_model}</Mono> quantifié en local.
                      </>
                    )}
                    {v3?.summary.false_refusals === 0 && " Aucun faux refus."}
                  </p>
                </div>
                <Link
                  to="/evaluation?tab=reponses"
                  className="inline-flex items-center gap-1.5 text-sm font-medium text-accent-ink underline-offset-4 hover:underline"
                >
                  Voir le détail des {report.data.datasets.nexalis_questions} questions
                  <ArrowRight size={14} aria-hidden="true" />
                </Link>
              </Card>
            </div>
            <StatTile
              label="Bonne source dans le top 5"
              value={fmt.pct(hybrid?.recall_at_5)}
              detail={`Recherche hybride, MRR ${fmt.dec2(hybrid?.mrr_at_10)}`}
            />
            <StatTile
              label="Hors périmètre refusés"
              value={`${v3?.summary.oos_refused}/${v3?.summary.oos_total}`}
              detail={`Dont ${v3?.summary.oos_without_llm} sans appeler le LLM`}
            />
            <StatTile
              label="Données personnelles bloquées"
              value={`${security?.blocked}/${security?.messages.length}`}
              detail={`${security?.false_positives} faux positif sur ${fmt.int(security?.legit_questions)} questions`}
            />
            <StatTile
              label="Tests automatisés"
              value={tests ? `${tests.passed}/${tests.total}` : "—"}
              detail={tests ? `En ${fmt.dec2(tests.seconds)} s, sans réseau ni modèle` : "Rapport pytest absent"}
            />
          </div>

          <SectionTitle hint="Tout tourne sur CPU, sauf la génération.">Le trajet d'une question.</SectionTitle>
          <Pipeline />

          <div className="mt-10 grid grid-cols-1 gap-4 lg:grid-cols-[1.1fr_1fr]">
            <Card>
              <CardHeader
                title="Configuration en service"
                description="Lue en direct sur l'API. Chaque valeur a été choisie par une mesure, voir l'onglet Évaluation."
              />
              {config.error ? (
                <div className="p-5">
                  <ErrorState error={config.error} onRetry={config.reload} />
                </div>
              ) : (
                <dl className="grid grid-cols-[minmax(0,auto)_minmax(0,1fr)] gap-x-6 gap-y-2.5 px-5 pt-4 pb-5 text-sm">
                  {config.data &&
                    (
                      [
                        ["LLM", <Mono key="llm">{`${config.data.llm.provider} · ${config.data.llm.model}`}</Mono>],
                        ["Température", fmt.dec2(config.data.llm.temperature)],
                        ["Embeddings", <Mono key="emb">{config.data.retrieval.embedding_model}</Mono>],
                        [
                          "Recherche",
                          config.data.retrieval.hybrid_search ? "Hybride BM25 + vecteurs (RRF)" : "Vecteurs seuls",
                        ],
                        ["Reranker", config.data.retrieval.reranker ? <Mono key="rr">{config.data.retrieval.reranker}</Mono> : "Désactivé (trop lent sur CPU)"],
                        ["Découpage", `${config.data.chunking.size} tokens, overlap ${config.data.chunking.overlap}`],
                        ["Extraits envoyés", `${config.data.retrieval.top_k} sur ${config.data.retrieval.fetch_k} candidats`],
                        ["Seuil de refus", `cosinus < ${fmt.dec2(config.data.retrieval.min_score)}`],
                        ["Versions obsolètes", config.data.retrieval.exclude_obsolete ? "Exclues" : "Incluses"],
                        ["Prompt", <Mono key="pv">{config.data.prompt_version}</Mono>],
                        [
                          "Sécurité",
                          `${config.data.security.auth_enabled ? "Clés d'API actives" : "Clés d'API désactivées (local)"}, ${config.data.security.rate_limit_per_minute} req/min`,
                        ],
                      ] as [string, React.ReactNode][]
                    ).map(([term, value]) => (
                      <div key={term} className="contents">
                        <dt className="text-ink-3">{term}</dt>
                        <dd className="min-w-0 break-words text-ink">{value}</dd>
                      </div>
                    ))}
                </dl>
              )}
            </Card>

            <Card>
              <CardHeader title="Avancement du projet" description="Les 9 itérations du plan d'action." />
              <ol className="grid grid-cols-1 gap-0 px-5 pt-3 pb-4">
                {ROADMAP.map((step) => {
                  const state = STATE[step.state];
                  const Glyph = state.icon;
                  return (
                    <li key={step.n} className="flex items-start gap-3 border-b border-line py-2.5 last:border-b-0">
                      <Glyph
                        size={18}
                        weight={step.state === "todo" ? "regular" : "fill"}
                        className={`mt-0.5 shrink-0 ${state.className}`}
                        aria-label={state.label}
                      />
                      <div className="min-w-0 flex-1">
                        <p className="text-sm text-ink">
                          <span className="tnum text-ink-3">{step.n}.</span> {step.title}
                        </p>
                        <p className="text-[13px] text-ink-3">{step.detail}</p>
                      </div>
                      <span className="shrink-0 text-xs text-ink-3">{state.label}</span>
                    </li>
                  );
                })}
              </ol>
            </Card>
          </div>

          <p className="mt-8 text-xs text-ink-3">
            Rapport d'évaluation généré le {fmt.dateTime(report.data.generated_at)} par{" "}
            <code>python -m scripts.export_reports</code>.
          </p>
        </>
      )}
    </>
  );
}
