import { MagnifyingGlass } from "@phosphor-icons/react";
import { useMemo, useState } from "react";
import { useSearchParams } from "react-router";
import { BarList, LineChartBlock, SERIES, StripPlot } from "../components/charts";
import { ErrorState } from "../components/ErrorState";
import { Markdown } from "../components/Markdown";
import { DataTable, TableView } from "../components/tables";
import {
  Badge,
  Card,
  CardHeader,
  LoadingBlock,
  Mono,
  PageHeader,
  QueryTabs,
  SegmentedControl,
  StatTile,
  StatusIcon,
} from "../components/ui";
import type { AnswerItem, AnswerRun, QuantizationRow, Report } from "../lib/api";
import { capitalize, fmt, fr } from "../lib/format";
import { useApi } from "../lib/hooks";

const TABS = [
  { id: "retrieval", label: "Recherche" },
  { id: "reponses", label: "Réponses" },
  { id: "modele", label: "Modèle" },
  { id: "securite", label: "Sécurité" },
];

export function EvaluationPage() {
  const report = useApi<Report>("/api/reports");
  const [params] = useSearchParams();
  const tab = params.get("tab") ?? "retrieval";

  return (
    <>
      <PageHeader
        title="Évaluation."
        description="Chaque choix du pipeline a été mesuré : taille des chunks, recherche hybride, seuil de refus, prompt. Les jeux de questions sont annotés à la main et versionnés dans eval/."
      />
      <QueryTabs tabs={TABS} label="Sections de l'évaluation" />
      {report.error ? (
        <ErrorState error={report.error} onRetry={report.reload} />
      ) : !report.data ? (
        <LoadingBlock />
      ) : tab === "reponses" ? (
        <AnswersTab report={report.data} />
      ) : tab === "modele" ? (
        <ModelTab report={report.data} />
      ) : tab === "securite" ? (
        <SecurityTab report={report.data} />
      ) : (
        <RetrievalTab report={report.data} />
      )}
    </>
  );
}

// ================================================================== recherche

const SIZES = ["256", "384", "512", "768", "1024", "section"];
const sizeLabel = (s: string) => (s === "section" ? "Par article" : `${s} tokens`);

function RetrievalTab({ report }: { report: Report }) {
  const { retrieval, retained } = report;
  const hybrid = retrieval.comparison.find((c) => c.key === "hybrid");
  const vector = retrieval.comparison.find((c) => c.key === "vector");

  const sizeRows = SIZES.map((size) => {
    const syntec = retrieval.syntec_grid.find((r) => r.chunk_size === size && Math.abs(r.overlap - (size === "section" ? 0 : 0.1)) < 1e-6);
    const nexalis = retrieval.nexalis_sizes.find((r) => r.chunk_size === size);
    return {
      size,
      syntec_r5: syntec?.recall_at_5 ?? null,
      nexalis_r5: nexalis?.recall_at_5 ?? null,
      syntec_mrr: syntec?.mrr_at_10 ?? null,
      nexalis_mrr: nexalis?.mrr_at_10 ?? null,
      syntec_ctx: syntec?.ctx_tokens_at_5 ?? null,
      nexalis_ctx: nexalis?.ctx_tokens_at_5 ?? null,
    };
  });

  const gating = retrieval.gating?.questions ?? [];
  const threshold = retained.min_score;
  const outCaught = gating.filter((q) => !q.in_scope && q.top_cosine < threshold).length;
  const outTotal = gating.filter((q) => !q.in_scope).length;
  const inLost = gating.filter((q) => q.in_scope && q.top_cosine < threshold).length;

  const bench = retrieval.reranker_bench?.results ?? [];

  return (
    <div className="grid grid-cols-1 gap-4">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile label="Bonne source dans le top 5" value={fmt.pct(hybrid?.recall_at_5)} detail={`Contre ${fmt.pct(vector?.recall_at_5)} en vecteurs seuls`} />
        <StatTile label="Rang moyen réciproque (MRR@10)" value={fmt.dec2(hybrid?.mrr_at_10)} detail={`Contre ${fmt.dec2(vector?.mrr_at_10)} en vecteurs seuls`} />
        <StatTile label="Bonne source dans le top 8" value={fmt.pct(hybrid?.recall_at_8)} detail={`${report.datasets.nexalis_questions - 10} questions Nexalis`} />
        <StatTile label="Contexte envoyé au LLM" value={`${fmt.int(hybrid?.ctx_tokens_at_5)}`} detail={"Tokens pour 5 extraits (objectif ≤ 2 500)"} />
      </div>

      <Card>
        <CardHeader
          title="Taille des chunks"
          description={
            <>
              Recall@5 pour chaque taille, en recherche vectorielle seule (overlap 10 %). Règle du plan : la plus petite
              taille à moins de 2 points du meilleur score. Retenu : <strong className="font-medium text-ink">{retained.chunk_size} tokens</strong>, qui envoie 26 % de
              tokens en moins au LLM que 512.
            </>
          }
        />
        <div className="grid grid-cols-1 gap-6 p-5 lg:grid-cols-2">
          <LineChartBlock
            ariaLabel="Recall@5 selon la taille des chunks, jeux Syntec et Nexalis"
            data={sizeRows}
            xKey="size"
            xLabel={sizeLabel}
            series={[
              { key: "syntec_r5", label: `Syntec (${report.datasets.syntec_questions} questions)`, color: SERIES[0] },
              { key: "nexalis_r5", label: "Nexalis (58 questions)", color: SERIES[1] },
            ]}
            yDomain={[0.9, 1]}
            yFormat={(n) => fmt.pct(n)}
          />
          <LineChartBlock
            ariaLabel="Tokens envoyés au LLM avec 5 extraits, selon la taille des chunks"
            data={sizeRows}
            xKey="size"
            xLabel={sizeLabel}
            series={[
              { key: "syntec_ctx", label: "Syntec", color: SERIES[0] },
              { key: "nexalis_ctx", label: "Nexalis", color: SERIES[1] },
            ]}
            yDomain={[0, 2200]}
            yFormat={(n) => fmt.int(n)}
          />
        </div>
        <TableView summary="Voir les valeurs">
          <DataTable
            caption="Recall@5, MRR@10 et tokens de contexte par taille de chunk"
            head={["Taille", "R@5 Syntec", "R@5 Nexalis", "MRR Syntec", "MRR Nexalis", "Tokens Syntec", "Tokens Nexalis"]}
            rows={sizeRows.map((r) => [
              sizeLabel(r.size),
              fmt.pct(r.syntec_r5),
              fmt.pct(r.nexalis_r5),
              fmt.dec3(r.syntec_mrr),
              fmt.dec3(r.nexalis_mrr),
              fmt.int(r.syntec_ctx),
              fmt.int(r.nexalis_ctx),
            ])}
            highlightRow={0}
          />
        </TableView>
      </Card>

      <Card>
        <CardHeader
          title="Recherche hybride contre rerankers"
          description="Les échecs restants étaient des mots exacts ratés par la recherche vectorielle (« astreinte », « déménager », « conjoint »). BM25 fusionné par RRF les retrouve, sans le coût d'un cross-encoder."
        />
        <div className="grid grid-cols-1 gap-6 p-5 lg:grid-cols-[1fr_1.2fr]">
          <div>
            <p className="mb-3 text-[13px] text-ink-3">MRR@10 sur les questions Nexalis, chunks de 256 tokens</p>
            <BarList
              label="MRR@10 par configuration"
              format={(n) => fmt.dec3(n)}
              rows={retrieval.comparison.map((c) => ({
                key: c.key,
                label: c.label,
                value: c.mrr_at_10,
                highlight: c.key === "hybrid",
                detail: `R@1 ${fmt.pct(c.recall_at_1)} · R@5 ${fmt.pct(c.recall_at_5)} · ${fmt.ms(c.latency_ms)} par question`,
              }))}
            />
          </div>
          <DataTable
            caption="Comparaison des configurations de recherche"
            head={["Configuration", "R@1", "R@5", "R@8", "MRR", "Latence"]}
            rows={retrieval.comparison.map((c) => [
              c.label,
              fmt.pct(c.recall_at_1),
              fmt.pct(c.recall_at_5),
              fmt.pct(c.recall_at_8),
              fmt.dec3(c.mrr_at_10),
              fmt.ms(c.latency_ms),
            ])}
            highlightRow={retrieval.comparison.findIndex((c) => c.key === "hybrid")}
          />
        </div>
        <p className="border-t border-line px-5 py-3 text-[13px] text-ink-3">
          Latence de recherche hors embedding de la question (~150 ms sur CPU). Sur le jeu Syntec, dont les questions
          paraphrasent le texte, l'hybride perd 2 points de recall@5 ; baisser le poids de BM25 ne les rattrape pas.
        </p>
      </Card>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader
            title="Coût d'un reranker sur CPU"
            description="Temps pour reclasser 20 passages, par question. Le reranker prévu au plan est inutilisable sur un conteneur CPU."
          />
          <div className="p-5">
            <BarList
              label="Secondes par question"
              max={16}
              format={(n) => (n < 0.1 ? fmt.ms(n * 1000) : `${fmt.dec2(n)} s`)}
              rows={[
                ...bench.map((b) => ({
                  key: `${b.model}-${b.max_length}`,
                  label: (
                    <>
                      <Mono>{b.model.split("/")[1]}</Mono> <span className="text-ink-3">· {b.max_length} tokens</span>
                    </>
                  ),
                  value: b.seconds_per_question,
                })),
                { key: "bm25", label: "BM25 + fusion RRF (retenu)", value: (hybrid?.latency_ms ?? 6) / 1000, highlight: true },
              ]}
            />
          </div>
        </Card>

        <Card>
          <CardHeader
            title="Seuil de refus sans LLM"
            description={`Meilleur score de chaque question. Sous ${fmt.dec2(threshold)}, l'assistant refuse directement : ${outCaught} hors-périmètre sur ${outTotal} écartés, ${inLost} question légitime perdue, autant de minutes GPU économisées.`}
          />
          <div className="p-5">
            <StripPlot
              ariaLabel="Score cosinus du meilleur extrait par question, avec le seuil de refus"
              points={gating.map((q) => ({ id: q.id, value: q.top_cosine, group: q.in_scope ? "in" : "out" }))}
              groups={[
                { id: "in", label: "Questions légitimes", color: SERIES[0] },
                { id: "out", label: "Hors périmètre", color: SERIES[1] },
              ]}
              threshold={threshold}
              domain={[0.3, 0.9]}
              format={(n) => fmt.dec2(n)}
            />
          </div>
        </Card>
      </div>
    </div>
  );
}

// ================================================================== réponses

function AnswersTab({ report }: { report: Report }) {
  const runs = report.answers.runs;
  const [params, setParams] = useSearchParams();
  const runId = params.get("run") ?? runs.at(-1)?.version ?? "";
  const run = runs.find((r) => r.version === runId) ?? runs.at(-1);
  if (!run) return null;
  const s = run.summary;

  return (
    <div className="grid grid-cols-1 gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <SegmentedControl
          label="Version du prompt"
          value={run.version}
          onChange={(value) => {
            const next = new URLSearchParams(params);
            next.set("run", value);
            setParams(next, { replace: true });
          }}
          options={runs.map((r) => ({ value: r.version, label: r.label }))}
        />
        <p className="text-[13px] text-ink-3">{run.note}</p>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile label="Réponses correctes" value={fmt.pct(s.accuracy)} detail={`${s.correct} sur ${s.evaluated} questions évaluées`} emphasis />
        <StatTile label="Faux refus" value={s.false_refusals} detail="Question légitime refusée à tort" emphasis />
        <StatTile label="Bon document cité" value={fmt.pct(s.source_cited)} detail="Dans les sources renvoyées" emphasis />
        <StatTile label="Hors périmètre refusés" value={`${s.oos_refused}/${s.oos_total}`} detail={`${s.oos_without_llm} sans appeler le LLM`} emphasis />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_1fr]">
        <Card>
          <CardHeader title="Par type de question" description="Les pièges testent la version en vigueur, les contradictions convention / accord et les informations présentes seulement dans un tableau." />
          <div className="p-5">
            <BarList
              label="Taux de réponses correctes par type"
              format={(n) => fmt.pct(n)}
              rows={Object.entries(s.by_type)
                .sort((a, b) => b[1].total - a[1].total)
                .map(([type, v]) => ({
                  key: type,
                  label: report.answers.type_labels[type] ?? type,
                  value: v.total ? v.correct / v.total : 0,
                  highlight: true,
                  detail: `${v.correct} sur ${v.total}`,
                }))}
            />
          </div>
        </Card>
        <Card>
          <CardHeader title="D'une version à l'autre" description="v3 ajoute une consigne : une question pratique fermée se répond par oui ou non à partir de la règle des extraits. La dernière colonne garde le prompt v3 et passe au modèle de production." />
          <div className="p-5">
            <DataTable
              caption="Comparaison des versions du prompt"
              head={["Métrique", ...runs.map((r) => r.version)]}
              rows={[
                ["Réponses correctes", ...runs.map((r) => `${fmt.pct1(r.summary.accuracy)} (${r.summary.correct}/${r.summary.evaluated})`)],
                ["Faux refus", ...runs.map((r) => String(r.summary.false_refusals))],
                ["Bon document cité", ...runs.map((r) => fmt.pct1(r.summary.source_cited))],
                ["Hors périmètre refusés", ...runs.map((r) => `${r.summary.oos_refused}/${r.summary.oos_total}`)],
                [
                  "Pièges « version obsolète »",
                  ...runs.map((r) => {
                    const t = r.summary.by_type.piege_version;
                    return t ? `${t.correct}/${t.total}` : "—";
                  }),
                ],
                ["Non évaluées (erreur technique)", ...runs.map((r) => String(r.summary.errors))],
              ]}
            />
            <p className="mt-3 text-[13px] text-ink-3">
              v2 et v3 : Ministral 3 3B quantifié 4 bits via Ollama, sur un portable. Le 8B bf16 sur ZeroGPU corrige les
              erreurs de lecture de tableau du 3B ; il reste une confusion de catégorie de salarié (sy-01).
            </p>
          </div>
        </Card>
      </div>

      <QuestionExplorer run={run} />
    </div>
  );
}

type Filter = "all" | "ko" | "pieges" | "oos";

function QuestionExplorer({ run }: { run: AnswerRun }) {
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  const items = useMemo(() => {
    const q = query.trim().toLowerCase();
    return run.items.filter((item) => {
      if (filter === "ko" && item.status === "ok") return false;
      if (filter === "pieges" && !item.type.startsWith("piege")) return false;
      if (filter === "oos" && item.type !== "hors_perimetre") return false;
      if (q && !`${item.id} ${item.question} ${item.answer ?? ""}`.toLowerCase().includes(q)) return false;
      return true;
    });
  }, [run, filter, query]);

  return (
    <Card>
      <CardHeader
        title="Les questions une par une"
        description="Réponse attendue, réponse du modèle et sources. Les critères vérifient les chiffres et termes attendus, ils n'ont pas été assouplis après coup."
      />
      <div className="flex flex-wrap items-center gap-3 px-5 pt-4">
        <SegmentedControl
          label="Filtrer les questions"
          value={filter}
          onChange={setFilter}
          options={[
            { value: "all", label: `Toutes (${run.items.length})` },
            { value: "ko", label: `À revoir (${run.items.filter((i) => i.status !== "ok").length})` },
            { value: "pieges", label: "Pièges" },
            { value: "oos", label: "Hors périmètre" },
          ]}
        />
        <label className="relative ml-auto w-full sm:w-64">
          <span className="sr-only">Rechercher une question</span>
          <MagnifyingGlass size={16} aria-hidden="true" className="absolute top-1/2 left-2.5 -translate-y-1/2 text-ink-3" />
          <input
            type="search"
            name="recherche-question"
            autoComplete="off"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Télétravail, mutuelle, it-02…"
            className="h-8 w-full rounded-md bg-surface pr-3 pl-8 text-sm shadow-[inset_0_0_0_1px_var(--line-strong)] placeholder:text-ink-3"
          />
        </label>
      </div>
      <ul className="mt-4 border-t border-line">
        {items.map((item) => (
          <QuestionRow key={item.id} item={item} />
        ))}
        {items.length === 0 && <li className="px-5 py-6 text-sm text-ink-3">Aucune question ne correspond à ce filtre.</li>}
      </ul>
    </Card>
  );
}

function QuestionRow({ item }: { item: AnswerItem }) {
  return (
    <li className="border-b border-line last:border-b-0">
      <details className="group">
        <summary className="flex cursor-pointer list-none items-center gap-3 px-5 py-3 transition-colors duration-150 hover:bg-surface-2 [&::-webkit-details-marker]:hidden">
          <StatusIcon status={item.status} />
          <Mono className="w-12 shrink-0 text-ink-3">{item.id}</Mono>
          <span className="min-w-0 flex-1 truncate text-sm text-ink">{fr(item.question)}</span>
          <span className="hidden shrink-0 md:block">
            <Badge>{item.type_label}</Badge>
          </span>
        </summary>
        <div className="grid grid-cols-1 gap-4 bg-surface-2 px-5 py-4 text-sm md:grid-cols-2">
          <div>
            <p className="mb-1 text-[13px] text-ink-3">Réponse attendue</p>
            <p className="text-ink-2">{fr(item.expected ?? "Refus : l'information n'est pas dans les documents.")}</p>
            {item.document && (
              <p className="mt-2 text-[13px] text-ink-3">
                Source attendue : <Mono>{item.document}</Mono>
              </p>
            )}
          </div>
          <div>
            <p className="mb-1 text-[13px] text-ink-3">Réponse du modèle</p>
            {item.error ? (
              <p className="text-ink-2">Non générée : erreur technique du LLM pendant l'évaluation.</p>
            ) : (
              <div className="text-ink-2">
                <Markdown text={item.answer ?? ""} />
              </div>
            )}
            <p className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[13px] text-ink-3">
              {item.latency_ms != null && <span className="tnum">{fmt.ms(item.latency_ms)}</span>}
              {item.prompt_tokens != null && <span className="tnum">{fmt.int(item.prompt_tokens)} tokens en entrée</span>}
              {!item.llm_called && <span>Refus sans appel au LLM</span>}
              {item.sources.length > 0 && (
                <span>
                  Sources : <Mono>{item.sources.join(", ")}</Mono>
                </span>
              )}
            </p>
          </div>
        </div>
      </details>
    </li>
  );
}

// ================================================================== modèle

/** « ministral-3:3b-instruct-2512-q4_K_M » → « 3B · q4_K_M » ; « ministral-3-8b-nf4 (ZeroGPU) » → « 8B · nf4 ». */
function variantLabel(model: string): string {
  const size = /(\d+)b/i.exec(model)?.[1];
  const quant = model.includes("ZeroGPU")
    ? /-(bf16|int8|nf4)\b/.exec(model)?.[1]
    : /-(q\d\w*)$/i.exec(model)?.[1];
  return size && quant ? `${size}B · ${quant}` : model;
}

function memoryLabel(row: QuantizationRow): string {
  if (row.backend === "zerogpu") return row.vram_gb != null ? `${fmt.dec1(row.vram_gb)} Go VRAM` : "—";
  if (row.memory_gb == null) return "—";
  return `${fmt.dec1(row.memory_gb)} Go (${fmt.pct(row.gpu_share ?? 0)} en VRAM)`;
}

function ModelTab({ report }: { report: Report }) {
  const rows = report.quantization;
  const local = rows.filter((r) => r.backend === "ollama");
  const cloud = rows.filter((r) => r.backend === "zerogpu");
  const zerogpuRun = report.answers.runs.find((r) => r.version === "zerogpu");
  const bestLocal = [...local].sort((a, b) => b.accuracy - a.accuracy)[0];
  const bf16 = cloud.find((r) => r.model.includes("bf16"));

  return (
    <div className="grid grid-cols-1 gap-4">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile
          label="8B bf16 sur ZeroGPU"
          value={zerogpuRun ? fmt.pct(zerogpuRun.summary.accuracy) : "—"}
          detail={zerogpuRun ? `${zerogpuRun.summary.correct} sur ${zerogpuRun.summary.evaluated} questions` : "Évaluation à lancer"}
          emphasis
        />
        <StatTile
          label="Temps GPU par réponse"
          value={zerogpuRun?.summary.generation_seconds_p50 != null ? `${fmt.dec1(zerogpuRun.summary.generation_seconds_p50)} s` : "—"}
          detail="Médiane mesurée dans le Space, base du calcul FinOps"
          emphasis
        />
        <StatTile
          label="VRAM du 8B en bf16"
          value={bf16?.vram_gb != null ? `${fmt.dec1(bf16.vram_gb)} Go` : "—"}
          detail="Pic mesuré : tient sur une L4 24 Go"
          emphasis
        />
        <StatTile
          label="Meilleur modèle local"
          value={bestLocal ? variantLabel(bestLocal.model) : "—"}
          detail={bestLocal ? `${bestLocal.correct}/${bestLocal.questions} sur l'échantillon, portable 4 Go de VRAM` : ""}
          emphasis
        />
      </div>

      {[
        {
          id: "zerogpu",
          rows: cloud,
          title: "Quantization du 8B sur ZeroGPU",
          description:
            "Même modèle (Ministral 3 8B) chargé en bf16, int8 et nf4 avec bitsandbytes. Aucune perte de qualité mesurée ; nf4 divise la VRAM par 2,6 pour 50 % de temps en plus, int8 est 5 fois plus lent. bf16 reste retenu sur ZeroGPU, où seul le temps GPU est décompté.",
        },
        {
          id: "ollama",
          rows: local,
          title: "Modèles GGUF en local (Ollama)",
          description:
            "Sur un portable avec 4 Go de VRAM : le 8B ne tient pas sur la carte et tourne surtout sur CPU. Le 3B en q8_0 est le meilleur compromis pour développer.",
        },
      ].map((bench) => (
        <Card key={bench.id}>
          <CardHeader title={bench.title} description={bench.description} />
          {bench.rows.length === 0 ? (
            <p className="px-5 py-6 text-sm text-ink-3">Banc d'essai pas encore lancé.</p>
          ) : (
            <div className="grid grid-cols-1 gap-6 p-5 lg:grid-cols-[1fr_1.4fr]">
              {bench.id === "zerogpu" ? (
                <div>
                  <p className="mb-3 text-[13px] text-ink-3">VRAM au pic ; toutes les variantes répondent juste à {bench.rows[0].questions} questions sur {bench.rows[0].questions}</p>
                  <BarList
                    label="VRAM au pic par variante, en gigaoctets"
                    max={24}
                    format={(n) => `${fmt.dec1(n)} Go`}
                    rows={bench.rows.map((r) => ({
                      key: r.model,
                      label: <Mono>{variantLabel(r.model)}</Mono>,
                      value: r.vram_gb ?? 0,
                      highlight: r.model.includes("nf4"),
                      detail: `${r.correct} sur ${r.questions} · ${fmt.dec1(r.generation_seconds_p50)} s de génération`,
                    }))}
                  />
                  <p className="mt-3 text-[13px] text-ink-3">Échelle : 24 Go, la mémoire d'une L4. En nf4, une T4 16 Go suffirait.</p>
                </div>
              ) : (
                <div>
                  <p className="mb-3 text-[13px] text-ink-3">Réponses correctes sur l'échantillon de {bench.rows[0].questions} questions</p>
                  <BarList
                    label="Taux de réponses correctes par variante"
                    format={(n) => fmt.pct(n)}
                    rows={bench.rows.map((r) => ({
                      key: r.model,
                      label: <Mono>{variantLabel(r.model)}</Mono>,
                      value: r.accuracy,
                      highlight: true,
                      detail: `${r.correct} sur ${r.questions}`,
                    }))}
                  />
                </div>
              )}
              <DataTable
                caption={`Comparaison des variantes : ${bench.title}`}
                head={["Variante", "Correctes", "Tokens/s", "Temps LLM (médiane)", "Mémoire"]}
                rows={bench.rows.map((r) => [
                  variantLabel(r.model),
                  `${r.correct}/${r.questions}`,
                  r.tokens_per_second != null ? fmt.dec1(r.tokens_per_second) : "—",
                  r.llm_seconds_p50 != null ? `${fmt.dec1(r.llm_seconds_p50)} s` : "—",
                  memoryLabel(r),
                ])}
              />
            </div>
          )}
        </Card>
      ))}
      <p className="text-[13px] text-ink-3">
        Échantillon fixe de 20 questions couvrant tous les types (factuelles, tableaux, calculs, pièges, hors périmètre),
        mêmes critères que l'évaluation complète. Script : <Mono>eval/compare_quantization.py</Mono>.
      </p>
    </div>
  );
}

// ================================================================== sécurité

function SecurityTab({ report }: { report: Report }) {
  const sec = report.security;
  const byType = Object.entries(
    sec.messages.reduce<Record<string, { total: number; blocked: number }>>((acc, m) => {
      const key = capitalize(m.label);
      acc[key] ??= { total: 0, blocked: 0 };
      acc[key].total += 1;
      acc[key].blocked += Number(m.blocked);
      return acc;
    }, {}),
  );
  return (
    <div className="grid grid-cols-1 gap-4">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <StatTile label="Messages avec données personnelles bloqués" value={`${sec.blocked}/${sec.messages.length}`} detail="Générés avec Faker (fr_FR)" emphasis />
        <StatTile label="Faux positifs" value={sec.false_positives} detail={`Sur ${fmt.int(sec.legit_questions)} questions légitimes (Nexalis + Syntec)`} emphasis />
        <StatTile label="Types détectés" value={byType.length} detail="Avec contrôle de clé, modulo 97 ou Luhn" emphasis />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1.5fr_1fr]">
        <Card>
          <CardHeader
            title="Messages de test"
            description="Affichés masqués, comme dans les journaux. Une question bloquée n'atteint ni l'index ni le modèle (HTTP 400 avec un message explicatif)."
          />
          <ul className="mt-4 border-t border-line">
            {sec.messages.map((m) => (
              <li key={m.id} className="flex items-start gap-3 border-b border-line px-5 py-2.5 last:border-b-0">
                <span className="mt-0.5">
                  <StatusIcon status={m.blocked ? "ok" : "ko"} />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-sm text-ink-2">{fr(m.masked ?? capitalize(m.label))}</p>
                  <p className="mt-0.5 text-xs text-ink-3">
                    <Mono>{m.id}</Mono> · attendu{"\u00a0"}: {m.label}
                  </p>
                </div>
              </li>
            ))}
          </ul>
        </Card>
        <div className="grid grid-cols-1 content-start gap-4">
          <Card>
            <CardHeader title="Par type de donnée" />
            <div className="p-5">
              <BarList
                label="Messages bloqués par type"
                format={(n) => fmt.pct(n)}
                rows={byType.map(([label, v]) => ({
                  key: label,
                  label,
                  value: v.blocked / v.total,
                  highlight: true,
                  detail: `${v.blocked} sur ${v.total}`,
                }))}
              />
            </div>
          </Card>
          <Card>
            <CardHeader title="Autres protections" />
            <ul className="grid grid-cols-1 gap-3 p-5 text-sm text-ink-2">
              {[
                ["Journaux", "Le texte des questions n'est jamais écrit ; un filtre masque toute donnée personnelle restante."],
                ["Clés d'API", "En-tête X-API-Key, rôles employé et admin (réindexation)."],
                ["Limite de débit", "30 requêtes par minute et par clé, réponse 429 au-delà."],
                ["Injection de prompt", "Extraits et question balisés, traités comme des données, jamais comme des instructions."],
                ["Minimisation", "Seuls la question et 5 extraits partent vers le modèle ; en local, rien ne sort du poste."],
              ].map(([title, text]) => (
                <li key={title}>
                  <span className="font-medium text-ink">{title}.</span> {text}
                </li>
              ))}
            </ul>
          </Card>
        </div>
      </div>
    </div>
  );
}
