import { CaretDown } from "@phosphor-icons/react";
import { ErrorState } from "../components/ErrorState";
import { Card, CardHeader, CodeLine, EmptyState, LoadingBlock, Mono, PageHeader, StatTile, StatusIcon } from "../components/ui";
import type { Report } from "../lib/api";
import { fmt, humanizeTest } from "../lib/format";
import { useApi } from "../lib/hooks";

const AREAS: Record<string, string> = {
  "tests/test_api.py": "API : routes, validation des entrées, erreurs du LLM, Swagger",
  "tests/test_chunking.py": "Découpage : titres, tokens, tableaux intacts, pages",
  "tests/test_rag.py": "Recherche et assistant : filtres, refus sans LLM, sources, streaming",
  "tests/test_lexical.py": "BM25 et fusion RRF de la recherche hybride",
  "tests/test_security.py": "RGPD et accès : données personnelles, clés, rôles, débit",
  "tests/test_tracking.py": "Suivi MLflow des requêtes et du feedback",
  "tests/test_dashboard.py": "Routes de l'interface web",
  "tests/test_ollama_client.py": "Client Ollama (serveur simulé)",
  "tests/test_mistral_client.py": "Client Mistral (SDK simulé)",
};

const COMMANDS: [string, string][] = [
  ["Tests unitaires et d'API", "pytest -q"],
  ["Grille de découpage, 100 questions Syntec", "python -m eval.eval_retrieval --dataset syntec --grid full"],
  ["Recherche hybride, questions Nexalis", "python -m eval.eval_retrieval --dataset nexalis --hybrid"],
  ["Seuil de refus sans LLM", "python -m eval.analyze_gating --output eval/results/gating.json"],
  ["Réponses de bout en bout", "python -m eval.eval_answers"],
  ["Rapport de cette interface", "python -m scripts.export_reports"],
];

export function TestsPage() {
  const report = useApi<Report>("/api/reports");
  const tests = report.data?.tests;

  return (
    <>
      <PageHeader
        title="Tests."
        description="Les tests tournent sans réseau ni modèle chargé : LLM, embeddings et serveurs sont remplacés par des faux objets. Ils protègent le contrat de l'API, le découpage et les garde-fous RGPD."
      />
      {report.error ? (
        <ErrorState error={report.error} onRetry={report.reload} />
      ) : !report.data ? (
        <LoadingBlock />
      ) : !tests ? (
        <EmptyState title="Rapport pytest absent.">
          Lancez <code>python -m scripts.export_reports</code> pour exécuter les tests et mettre à jour cette page.
        </EmptyState>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <StatTile label="Tests réussis" value={`${tests.passed}/${tests.total}`} emphasis />
            <StatTile label="Échecs" value={tests.failed} emphasis />
            <StatTile label="Durée" value={`${fmt.dec2(tests.seconds)} s`} emphasis />
            <StatTile label="Fichiers de tests" value={tests.files.length} detail={`Exécutés le ${fmt.dateTime(tests.timestamp)}`} emphasis />
          </div>

          <div className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-[1.4fr_1fr]">
            <Card>
              <CardHeader title="Ce que couvrent les tests" description="Ouvrez un fichier pour voir chaque test et son résultat." />
              <ul className="mt-4 border-t border-line">
                {tests.files
                  .slice()
                  .sort((a, b) => b.tests.length - a.tests.length)
                  .map((file) => {
                    const failed = file.tests.filter((t) => t.status === "failed").length;
                    return (
                      <li key={file.file} className="border-b border-line last:border-b-0">
                        <details className="group">
                          <summary className="flex cursor-pointer list-none items-center gap-3 px-5 py-3 transition-colors duration-150 hover:bg-surface-2 [&::-webkit-details-marker]:hidden">
                            <StatusIcon status={failed ? "failed" : "passed"} />
                            <span className="min-w-0 flex-1">
                              <span className="block truncate text-sm text-ink">{AREAS[file.file] ?? file.file}</span>
                              <Mono className="text-ink-3">{file.file}</Mono>
                            </span>
                            <span className="shrink-0 tnum text-sm text-ink-2">
                              {file.tests.length - failed}/{file.tests.length}
                            </span>
                            <CaretDown size={14} aria-hidden="true" className="shrink-0 text-ink-3 transition-transform duration-150 group-open:rotate-180" />
                          </summary>
                          <ul className="grid grid-cols-1 gap-1 bg-surface-2 px-5 py-3">
                            {file.tests.map((test) => (
                              <li key={test.name} className="flex items-start gap-2.5 text-[13px]">
                                <span className="mt-0.5">
                                  <StatusIcon status={test.status} />
                                </span>
                                <span className="min-w-0 flex-1 text-ink-2">{humanizeTest(test.name)}</span>
                                <span className="shrink-0 tnum text-ink-3">{fmt.ms(test.seconds * 1000)}</span>
                              </li>
                            ))}
                          </ul>
                        </details>
                      </li>
                    );
                  })}
              </ul>
            </Card>

            <Card className="self-start">
              <CardHeader title="Relancer les mesures" description="Depuis la racine du projet, environnement virtuel activé." />
              <ul className="grid grid-cols-1 gap-4 p-5">
                {COMMANDS.map(([label, command]) => (
                  <li key={command} className="grid grid-cols-1 gap-1.5">
                    <span className="text-[13px] text-ink-2">{label}</span>
                    <CodeLine>{command}</CodeLine>
                  </li>
                ))}
              </ul>
            </Card>
          </div>
        </>
      )}
    </>
  );
}
