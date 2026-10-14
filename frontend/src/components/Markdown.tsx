import { Fragment, type ReactNode } from "react";
import { fr } from "../lib/format";

/**
 * Rendu Markdown minimal des réponses du LLM (gras, italique, listes, paragraphes) sans
 * injecter de HTML. Les citations [document.pdf] deviennent des puces cliquables.
 */
export function Markdown({
  text,
  onCite,
}: {
  text: string;
  onCite?: (document: string) => void;
}) {
  const blocks = text.replace(/\r\n/g, "\n").split(/\n{2,}/);
  return (
    <div className="grid grid-cols-1 gap-3 break-words">
      {blocks.map((block, i) => {
        const lines = block.split("\n").filter((line) => line.trim());
        if (lines.length && lines.every((line) => /^\s*([-*•]|\d+[.)])\s+/.test(line))) {
          const ordered = /^\s*\d/.test(lines[0]);
          const Tag = ordered ? "ol" : "ul";
          return (
            <Tag key={i} className={ordered ? "grid list-decimal gap-1 pl-5" : "grid list-disc gap-1 pl-5"}>
              {lines.map((line, j) => (
                <li key={j} className="pl-1 marker:text-ink-3">
                  {inline(line.replace(/^\s*([-*•]|\d+[.)])\s+/, ""), onCite)}
                </li>
              ))}
            </Tag>
          );
        }
        return (
          <p key={i}>
            {lines.map((line, j) => (
              <Fragment key={j}>
                {j > 0 && <br />}
                {inline(line.replace(/^#{1,6}\s+/, ""), onCite)}
              </Fragment>
            ))}
          </p>
        );
      })}
    </div>
  );
}

const TOKEN = /(\*\*[^*]+\*\*|\*[^*\s][^*]*\*|\[[^\[\]]+?\.(?:pdf|docx|md|txt|pptx|html)(?:,[^\]]*)?\])/g;

function inline(text: string, onCite?: (document: string) => void): ReactNode[] {
  return text.split(TOKEN).map((part, i) => {
    if (!part) return null;
    if (part.startsWith("**")) return <strong key={i} className="font-semibold text-ink">{part.slice(2, -2)}</strong>;
    if (part.startsWith("*") && part.endsWith("*")) return <em key={i}>{part.slice(1, -1)}</em>;
    if (part.startsWith("[") && part.endsWith("]")) {
      const document = part.slice(1, -1).split(",")[0].trim();
      return (
        <button
          key={i}
          type="button"
          onClick={() => onCite?.(document)}
          title={`Voir la source ${document}`}
          className="mx-0.5 inline-flex h-5 max-w-full items-center rounded-full bg-surface-2 px-2 align-[1px] font-mono text-[11px] text-ink-2 transition-[background-color,color] duration-150 hover:bg-surface-3 hover:text-ink"
        >
          <span className="truncate" translate="no">
            {document}
          </span>
        </button>
      );
    }
    return <Fragment key={i}>{fr(part)}</Fragment>;
  });
}
