import {
  ArrowRight,
  Brain,
  Funnel,
  MagnifyingGlass,
  Quotes,
  ShieldCheck,
  TextAlignLeft,
  type Icon,
} from "@phosphor-icons/react";
import { Fragment } from "react";
import { cx } from "./ui";

interface Step {
  icon: Icon;
  title: string;
  detail: string;
  where: "CPU" | "GPU";
}

const STEPS: Step[] = [
  { icon: ShieldCheck, title: "Filtre RGPD", detail: "NIR, IBAN, carte, e-mail, téléphone bloqués", where: "CPU" },
  { icon: MagnifyingGlass, title: "Recherche hybride", detail: "BGE-M3 + BM25, fusion RRF, 20 candidats", where: "CPU" },
  { icon: Funnel, title: "Seuil de pertinence", detail: "Sous 0,42 : refus sans appeler le LLM", where: "CPU" },
  { icon: TextAlignLeft, title: "Prompt", detail: "5 extraits balisés, règles anti-injection", where: "CPU" },
  { icon: Brain, title: "Génération", detail: "Ministral 3 (Ollama en local, ZeroGPU en prod)", where: "GPU" },
  { icon: Quotes, title: "Réponse sourcée", detail: "Document, section, page + suivi MLflow", where: "CPU" },
];

/** Le pipeline d'une question : tout est sur CPU sauf la génération. */
export function Pipeline() {
  return (
    <ol className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-[repeat(11,auto)] xl:items-stretch xl:gap-0" aria-label="Étapes du traitement d'une question">
      {STEPS.map((step, i) => {
        const Glyph = step.icon;
        return (
          <Fragment key={step.title}>
            <li
              className={cx(
                "reveal flex min-w-0 gap-3 rounded-lg p-4 xl:flex-col xl:gap-2",
                step.where === "GPU" ? "bg-ink text-bg" : "bg-surface shadow-[inset_0_0_0_1px_var(--line)]",
              )}
              style={{ "--i": i } as React.CSSProperties}
            >
              <Glyph size={20} weight="regular" aria-hidden="true" className="shrink-0" />
              <div className="min-w-0">
                <p className="text-sm font-medium">{step.title}</p>
                <p className={cx("mt-0.5 text-[13px] leading-[18px]", step.where === "GPU" ? "text-bg/70" : "text-ink-3")}>
                  {step.detail}
                </p>
                <p className={cx("mt-2 text-xs font-medium", step.where === "GPU" ? "text-bg/80" : "text-ink-2")}>
                  {step.where === "GPU" ? "GPU" : "CPU"}
                </p>
              </div>
            </li>
            {i < STEPS.length - 1 && (
              <li aria-hidden="true" className="hidden items-center justify-center px-1.5 text-ink-3 xl:flex">
                <ArrowRight size={14} />
              </li>
            )}
          </Fragment>
        );
      })}
    </ol>
  );
}
