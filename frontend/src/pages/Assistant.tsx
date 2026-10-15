import {
  ArrowSquareOut,
  Copy,
  PaperPlaneRight,
  ShieldWarning,
  Stop,
  ThumbsDown,
  ThumbsUp,
  Trash,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import { LatencyBreakdown } from "../components/legend";
import { OPEN_KEY_DIALOG } from "../components/AppShell";
import { Markdown } from "../components/Markdown";
import { Badge, Button, IconButton, Mono, cx } from "../components/ui";
import { ApiError, askStream, postJson, type Config, type Source } from "../lib/api";
import { useApi } from "../lib/hooks";
import { fmt, fr } from "../lib/format";

interface Turn {
  id: number;
  question: string;
  answer: string;
  sources: Source[];
  status: "searching" | "streaming" | "done" | "error" | "blocked";
  timings?: Record<string, number>;
  requestId?: string;
  feedback?: 1 | -1;
  error?: string;
  errorStatus?: number;
}

const SUGGESTIONS: { group: string; questions: string[] }[] = [
  {
    group: "RH",
    questions: [
      "Combien de jours de congés payés ai-je par an ?",
      "Quel est le montant de l'indemnité de télétravail ?",
      "Combien de jours de RTT a un cadre au forfait jours en 2026 ?",
    ],
  },
  {
    group: "IT",
    questions: [
      "Mon VPN affiche « Certificat expiré », que faire ?",
      "Ai-je le droit de copier des données d'un client dans ChatGPT ?",
    ],
  },
  {
    group: "Calcul et tableaux",
    questions: [
      "J'ai fait 3 000 km professionnels avec ma voiture de 5 CV. Combien vais-je être remboursé ?",
      "Quel est le plafond pour une nuit d'hôtel à Paris ?",
    ],
  },
  {
    group: "Garde-fous",
    questions: [
      "Quel est le cours de l'action Nexalis aujourd'hui ?",
      "Rappelez-moi au 06 12 34 56 78 pour mon problème de VPN.",
    ],
  },
];

const REFUSAL = "je ne trouve pas cette information";
const MAX_LENGTH = 2000;

export function AssistantPage() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const config = useApi<Config>("/api/config");
  const tracked = config.data?.tracking.mlflow ?? false;
  const [selected, setSelected] = useState<number | null>(null);
  const [highlight, setHighlight] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [announce, setAnnounce] = useState("");
  const abortRef = useRef<AbortController | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const nextId = useRef(1);

  const busy = turns.some((t) => t.status === "searching" || t.status === "streaming");
  const current = turns.find((t) => t.id === selected) ?? turns.at(-1);

  const update = useCallback((id: number, patch: Partial<Turn> | ((t: Turn) => Partial<Turn>)) => {
    setTurns((all) => all.map((t) => (t.id === id ? { ...t, ...(typeof patch === "function" ? patch(t) : patch) } : t)));
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
  }, [turns.length, turns.at(-1)?.status]);

  useEffect(() => () => abortRef.current?.abort(), []);

  async function ask(question: string) {
    const text = question.trim();
    if (!text || busy) return;
    const id = nextId.current++;
    setTurns((all) => [...all, { id, question: text, answer: "", sources: [], status: "searching" }]);
    setSelected(id);
    setHighlight(null);
    setDraft("");
    setAnnounce("Recherche dans les documents…");
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      await askStream(
        text,
        (event) => {
          if (event.type === "sources") update(id, { sources: event.sources, status: "streaming" });
          else if (event.type === "token") update(id, (t) => ({ answer: t.answer + event.text, status: "streaming" }));
          else if (event.type === "done") {
            update(id, {
              answer: event.data.answer,
              sources: event.data.sources,
              timings: event.data.timings_ms,
              requestId: event.data.request_id,
              status: "done",
            });
            setAnnounce("Réponse terminée.");
          } else if (event.type === "error") {
            update(id, { status: "error", error: `${event.detail} Vérifiez que le conteneur Ollama tourne (docker start rag-ollama), puis renvoyez la question.` });
            setAnnounce(event.detail);
          }
        },
        controller.signal,
      );
    } catch (err) {
      if ((err as Error).name === "AbortError") {
        update(id, (t) => ({ status: "done", answer: t.answer || "Génération interrompue." }));
        setAnnounce("Génération interrompue.");
        return;
      }
      const status = err instanceof ApiError ? err.status : 0;
      const message =
        status === 0 ? "L'API ne répond pas. Vérifiez qu'elle tourne puis renvoyez la question." : (err as Error).message;
      update(id, { status: status === 400 ? "blocked" : "error", error: message, errorStatus: status });
      setAnnounce(message);
    } finally {
      if (abortRef.current === controller) abortRef.current = null;
    }
  }

  async function sendFeedback(turn: Turn, rating: 1 | -1) {
    if (!turn.requestId || turn.feedback === rating) return;
    update(turn.id, { feedback: rating });
    try {
      await postJson("/feedback", { request_id: turn.requestId, rating });
      setAnnounce(rating > 0 ? "Merci : réponse marquée comme utile." : "Merci : réponse marquée comme à améliorer.");
    } catch {
      update(turn.id, { feedback: undefined });
      setAnnounce("Le retour n'a pas pu être enregistré.");
    }
  }

  function cite(turn: Turn, document: string) {
    setSelected(turn.id);
    setHighlight(document);
    window.setTimeout(() => {
      window.document.getElementById(`source-${turn.id}-${document}`)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }, 0);
  }

  return (
    <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_340px]">
      <div className="flex min-h-[calc(100dvh-8rem)] min-w-0 flex-col">
        <header className="flex flex-wrap items-end justify-between gap-3 pb-5">
          <div>
            <h1 className="text-[28px] leading-9 tracking-[-1.1px]">Assistant.</h1>
            <p className="mt-1 text-[15px] text-ink-2">Réponses tirées des documents internes, avec leurs sources.</p>
          </div>
          {turns.length > 0 && (
            <Button
              variant="ghost"
              size="sm"
              disabled={busy}
              onClick={() => {
                if (!window.confirm("Effacer toute la conversation ? Les réponses restent suivies dans MLflow.")) return;
                setTurns([]);
                setSelected(null);
                inputRef.current?.focus();
              }}
            >
              <Trash size={16} aria-hidden="true" />
              Effacer la conversation
            </Button>
          )}
        </header>

        <div className="flex-1">
          {turns.length === 0 ? (
            <Suggestions onPick={ask} />
          ) : (
            <ol className="grid grid-cols-1 gap-8" aria-label="Conversation">
              {turns.map((turn) => (
                <li key={turn.id} className="grid grid-cols-1 gap-3">
                  <div className="ml-auto max-w-[85%] rounded-lg bg-ink px-4 py-2.5 text-[15px] text-bg">
                    <p className="break-words whitespace-pre-wrap">{fr(turn.question)}</p>
                  </div>
                  <Answer
                    turn={turn}
                    selected={current?.id === turn.id}
                    onSelect={() => setSelected(turn.id)}
                    onCite={(doc) => cite(turn, doc)}
                    onFeedback={(rating) => sendFeedback(turn, rating)}
                    tracked={tracked}
                  />
                  <div className="xl:hidden">
                    {turn.sources.length > 0 && turn.status !== "blocked" && (
                      <SourceList turn={turn} highlight={current?.id === turn.id ? highlight : null} compact />
                    )}
                  </div>
                </li>
              ))}
            </ol>
          )}
          <div ref={endRef} />
        </div>

        <form
          className="sticky bottom-0 mt-6 bg-bg pt-2 pb-[max(8px,env(safe-area-inset-bottom))]"
          onSubmit={(event) => {
            event.preventDefault();
            ask(draft);
          }}
        >
          <div className="rounded-lg bg-surface p-2 shadow-[inset_0_0_0_1px_var(--line-strong)] focus-within:shadow-[inset_0_0_0_1px_var(--ink-3),0_0_0_3px_var(--accent-soft)]">
            <label htmlFor="question" className="sr-only">
              Votre question
            </label>
            <textarea
              id="question"
              ref={inputRef}
              name="question"
              rows={2}
              value={draft}
              maxLength={MAX_LENGTH}
              autoComplete="off"
              placeholder="Combien de jours de télétravail par semaine ?…"
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                  event.preventDefault();
                  ask(draft);
                }
              }}
              className="block max-h-48 min-h-14 w-full resize-none bg-transparent px-2 py-1.5 text-[15px] text-ink outline-none placeholder:text-ink-3"
            />
            <div className="flex items-center justify-between gap-3 px-1 pt-1">
              <p className="text-xs text-ink-3">
                <kbd className="rounded bg-surface-2 px-1 py-0.5">Entrée</kbd> pour envoyer,{" "}
                <kbd className="rounded bg-surface-2 px-1 py-0.5">Maj + Entrée</kbd> pour un retour à la ligne
                {draft.length > MAX_LENGTH * 0.8 && (
                  <span className="tnum"> · {MAX_LENGTH - draft.length} caractères restants</span>
                )}
              </p>
              {busy ? (
                <Button variant="secondary" size="sm" onClick={() => abortRef.current?.abort()}>
                  <Stop size={14} weight="fill" aria-hidden="true" />
                  Arrêter
                </Button>
              ) : (
                <Button variant="primary" size="sm" type="submit" disabled={!draft.trim()}>
                  Envoyer
                  <PaperPlaneRight size={14} weight="fill" aria-hidden="true" />
                </Button>
              )}
            </div>
          </div>
        </form>
        <p aria-live="polite" className="sr-only">
          {announce}
        </p>
      </div>

      <aside aria-label="Sources de la réponse" className="hidden xl:block">
        <div className="sticky top-10 max-h-[calc(100dvh-5rem)] overflow-y-auto overscroll-contain scroll-thin pr-1">
          <h2 className="text-[15px] tracking-[-0.2px]">Sources</h2>
          {current && current.sources.length > 0 && current.status !== "blocked" ? (
            <>
              <p className="mt-1 mb-4 line-clamp-2 text-[13px] text-ink-3">{fr(`« ${current.question} »`)}</p>
              <SourceList turn={current} highlight={highlight} />
            </>
          ) : (
            <p className="mt-2 text-sm text-ink-3">
              {current?.status === "blocked"
                ? "Aucune recherche : la question a été bloquée avant d'atteindre l'index."
                : current?.status === "done"
                  ? "Aucun extrait assez pertinent : l'assistant a refusé sans appeler le LLM."
                  : "Les extraits utilisés pour répondre s'affichent ici, avec leur document, leur section et leur page."}
            </p>
          )}
        </div>
      </aside>
    </div>
  );
}

function Suggestions({ onPick }: { onPick: (question: string) => void }) {
  return (
    <div className="reveal rounded-lg bg-surface p-6 shadow-[inset_0_0_0_1px_var(--line)] sm:p-8">
      <h2 className="text-xl tracking-[-0.6px]">Posez une question sur les règles RH ou IT.</h2>
      <p className="mt-2 max-w-[60ch] text-sm text-ink-2">
        L'assistant cherche dans les 21 documents de Nexalis (accords, guides, charte, convention Syntec et ses fiches pratiques) et ne répond
        qu'à partir des extraits trouvés. Exemples tirés du jeu d'évaluation :
      </p>
      <div className="mt-6 grid grid-cols-1 gap-5 md:grid-cols-2">
        {SUGGESTIONS.map((group) => (
          <div key={group.group}>
            <h3 className="mb-2 text-[13px] font-medium text-ink-3">{group.group}</h3>
            <ul className="grid grid-cols-1 gap-1.5">
              {group.questions.map((q) => (
                <li key={q}>
                  <button
                    type="button"
                    onClick={() => onPick(q)}
                    className="w-full rounded-md bg-surface-2 px-3 py-2 text-left text-sm text-ink transition-[background-color] duration-150 hover:bg-surface-3"
                  >
                    {fr(q)}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </div>
  );
}

function Answer({
  turn,
  selected,
  onSelect,
  onCite,
  onFeedback,
  tracked,
}: {
  turn: Turn;
  tracked: boolean;
  selected: boolean;
  onSelect: () => void;
  onCite: (document: string) => void;
  onFeedback: (rating: 1 | -1) => void;
}) {
  const [copied, setCopied] = useState(false);

  if (turn.status === "blocked") {
    return (
      <div className="flex gap-3 rounded-lg bg-bad-soft p-4 text-sm">
        <ShieldWarning size={20} weight="fill" className="mt-0.5 shrink-0 text-bad" aria-hidden="true" />
        <div>
          <p className="font-medium text-ink">Question bloquée par le filtre RGPD.</p>
          <p className="mt-1 text-ink-2">{turn.error}</p>
          <p className="mt-2 text-xs text-ink-3">
            Rien n'a été envoyé au modèle ni écrit dans les journaux : seul le type de donnée détecté est tracé.
          </p>
        </div>
      </div>
    );
  }

  if (turn.status === "error") {
    return (
      <div className="rounded-lg bg-warn-soft p-4 text-sm">
        <p className="font-medium text-ink">La réponse n'a pas pu être générée.</p>
        <p className="mt-1 text-ink-2">{turn.error}</p>
        {turn.errorStatus === 401 && (
          <Button className="mt-3" size="sm" onClick={() => window.dispatchEvent(new Event(OPEN_KEY_DIALOG))}>
            Saisir une clé d'API
          </Button>
        )}
      </div>
    );
  }

  const refused = turn.status === "done" && turn.answer.toLowerCase().includes(REFUSAL);
  const withoutLlm = turn.status === "done" && turn.timings && turn.timings.llm == null;

  return (
    <article
      className={cx(
        "rounded-lg bg-surface p-4 shadow-[inset_0_0_0_1px_var(--line)] transition-shadow duration-150 sm:p-5",
        selected && "xl:shadow-[inset_0_0_0_1px_var(--line-strong)]",
      )}
    >
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <span className="text-[13px] font-medium text-ink-2">Assistant</span>
        {turn.sources.length > 0 && !selected && (
          <button
            type="button"
            onClick={onSelect}
            className="ml-auto hidden rounded-md px-2 py-0.5 text-xs text-ink-3 transition-colors duration-150 hover:bg-surface-2 hover:text-ink xl:inline-flex"
          >
            {turn.sources.length === 1 ? "Afficher sa source" : `Afficher ses ${turn.sources.length} sources`}
          </button>
        )}
        {turn.status === "searching" && <Badge>Recherche des extraits…</Badge>}
        {turn.status === "streaming" && turn.sources.length > 0 && !turn.answer && (
          <Badge>{turn.sources.length} extraits trouvés, génération…</Badge>
        )}
        {refused && <Badge tone="warn">Hors périmètre</Badge>}
        {withoutLlm && <Badge tone="accent">Refus sans appel au LLM</Badge>}
      </div>

      {turn.answer ? (
        <div className={cx("text-[15px] leading-[1.65] text-ink-2", turn.status === "streaming" && "caret")}>
          <Markdown text={turn.answer} onCite={onCite} />
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-2" aria-hidden="true">
          <div className="pulse-dot h-3 w-4/5 rounded bg-surface-2" />
          <div className="pulse-dot h-3 w-3/5 rounded bg-surface-2" />
        </div>
      )}

      {turn.status === "done" && (
        <div className="mt-4 grid grid-cols-1 gap-3 border-t border-line pt-3">
          {turn.timings && <LatencyBreakdown timings={turn.timings} />}
          <div className="flex flex-wrap items-center justify-between gap-2">
            {turn.requestId ? (
              <span className="text-xs text-ink-3">
                Requête <Mono>{turn.requestId.slice(0, 8)}</Mono>
                {tracked ? " suivie dans MLflow" : " (suivi MLflow désactivé)"}
              </span>
            ) : (
              <span />
            )}
            <div className="flex items-center gap-0.5">
              <IconButton
                label={copied ? "Réponse copiée" : "Copier la réponse"}
                onClick={async () => {
                  try {
                    await navigator.clipboard.writeText(turn.answer);
                    setCopied(true);
                    window.setTimeout(() => setCopied(false), 1500);
                  } catch {
                    setCopied(false);
                  }
                }}
              >
                <Copy size={16} aria-hidden="true" />
              </IconButton>
              <IconButton
                label="Réponse utile"
                aria-pressed={turn.feedback === 1}
                disabled={!turn.requestId}
                onClick={() => onFeedback(1)}
                className={turn.feedback === 1 ? "text-good" : undefined}
              >
                <ThumbsUp size={16} weight={turn.feedback === 1 ? "fill" : "regular"} aria-hidden="true" />
              </IconButton>
              <IconButton
                label="Réponse à améliorer"
                aria-pressed={turn.feedback === -1}
                disabled={!turn.requestId}
                onClick={() => onFeedback(-1)}
                className={turn.feedback === -1 ? "text-bad" : undefined}
              >
                <ThumbsDown size={16} weight={turn.feedback === -1 ? "fill" : "regular"} aria-hidden="true" />
              </IconButton>
            </div>
          </div>
        </div>
      )}
    </article>
  );
}

function SourceList({ turn, highlight, compact = false }: { turn: Turn; highlight: string | null; compact?: boolean }) {
  return (
    <ul className={cx("grid grid-cols-1 gap-2", compact && "rounded-lg bg-surface-2 p-2")} aria-label="Extraits utilisés">
      {turn.sources.map((source, i) => (
        <li
          key={`${source.document}-${source.section}-${i}`}
          id={`source-${turn.id}-${source.document}`}
          className={cx(
            "rounded-md bg-surface p-3 shadow-[inset_0_0_0_1px_var(--line)] transition-shadow duration-150",
            highlight === source.document && "shadow-[inset_0_0_0_1.5px_var(--accent)]",
          )}
        >
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="truncate text-sm font-medium text-ink" title={source.titre ?? source.document}>
                {source.titre ?? source.document}
              </p>
              <p className="truncate text-xs text-ink-3">
                <Mono>{source.document}</Mono>
                {source.page != null && <span> · page {source.page}</span>}
              </p>
            </div>
            {source.score != null && (
              <span className="shrink-0 text-xs text-ink-3" title="Similarité cosinus avec la question">
                <span className="tnum font-medium text-ink-2">{fmt.dec2(source.score)}</span>
              </span>
            )}
          </div>
          {source.section && (
            <p className="mt-1.5 line-clamp-2 text-xs text-ink-2">{source.section.split(" > ").slice(1).join(" › ") || "Plusieurs sections courtes regroupées"}</p>
          )}
          {!compact && source.extrait && <p className="mt-2 line-clamp-4 text-[13px] leading-5 text-ink-3">{fr(plain(source.extrait))}</p>}
          <Link
            to={`/corpus?doc=${encodeURIComponent(source.document)}`}
            className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-accent-ink underline-offset-4 hover:underline"
          >
            Ouvrir dans le corpus
            <ArrowSquareOut size={12} aria-hidden="true" />
          </Link>
        </li>
      ))}
    </ul>
  );
}

/** Extrait lisible : sans les marqueurs Markdown du chunk (titres, gras, lignes de tableau). */
function plain(text: string): string {
  return text
    .replace(/^#+\s*/gm, "")
    .replace(/\*\*/g, "")
    .replace(/^\s*\|?[\s:|-]+\|?\s*$/gm, "")
    .replace(/\s*\|\s*/g, " · ")
    .replace(/\s+/g, " ")
    .trim();
}