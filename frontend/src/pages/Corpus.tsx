import { CaretRight, FileDoc, FilePdf, FileText, Scan } from "@phosphor-icons/react";
import { useState } from "react";
import { Link, useSearchParams } from "react-router";
import { ErrorState } from "../components/ErrorState";
import { Badge, Card, EmptyState, LoadingBlock, Mono, PageHeader, Skeleton, StatTile, cx } from "../components/ui";
import type { ChunkInfo, DocumentInfo } from "../lib/api";
import { fmt } from "../lib/format";
import { useApi } from "../lib/hooks";

const FORMAT: Record<string, { label: string; icon: typeof FilePdf }> = {
  pdf: { label: "PDF", icon: FilePdf },
  pdf_scan: { label: "PDF scanné", icon: Scan },
  docx: { label: "Word", icon: FileDoc },
  md: { label: "Markdown", icon: FileText },
};

export function CorpusPage() {
  const docs = useApi<DocumentInfo[]>("/api/documents");
  const [params] = useSearchParams();
  const selectedName = params.get("doc");
  const selected = docs.data?.find((d) => d.document === selectedName) ?? null;

  const totals = docs.data?.reduce(
    (acc, d) => ({ chunks: acc.chunks + (d.chunks ?? 0), tokens: acc.tokens + (d.tokens ?? 0) }),
    { chunks: 0, tokens: 0 },
  );

  return (
    <>
      <PageHeader
        title="Corpus."
        description="Les documents internes de Nexalis Conseil, entreprise fictive dont chaque règle s'appuie sur une source publique citée. Formats volontairement mélangés pour tester le parsing, dont un scan lu par OCR."
      />
      {docs.error ? (
        <ErrorState error={docs.error} onRetry={docs.reload} />
      ) : !docs.data ? (
        <LoadingBlock />
      ) : (
        <>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <StatTile label="Documents" value={docs.data.length} detail="1 version obsolète conservée pour le test" />
            <StatTile label="Chunks indexés" value={totals?.chunks ? fmt.int(totals.chunks) : "—"} detail="256 tokens, découpés par titres" />
            <StatTile label="Tokens BGE-M3" value={totals?.tokens ? fmt.int(totals.tokens) : "—"} detail="Comptés avec le tokenizer du modèle" />
            <StatTile label="Formats" value="4" detail="PDF, scan, Word, Markdown" />
          </div>

          <div className="mt-8 grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1.05fr)_minmax(0,1fr)]">
            <Card className="overflow-hidden">
              <table className="w-full table-fixed text-sm">
                <caption className="sr-only">Documents du corpus</caption>
                <thead>
                  <tr className="bg-surface-2 text-left text-[13px] text-ink-3">
                    <th scope="col" className="px-4 py-2.5 font-normal">
                      Document
                    </th>
                    <th scope="col" className="hidden w-28 px-3 py-2.5 font-normal sm:table-cell">
                      Version
                    </th>
                    <th scope="col" className="w-24 px-4 py-2.5 text-right font-normal">
                      Chunks
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {docs.data.map((doc) => {
                    const format = FORMAT[doc.format ?? ""] ?? FORMAT.md;
                    const Glyph = format.icon;
                    const active = doc.document === selectedName;
                    return (
                      <tr key={doc.document} className={cx("border-t border-line", active && "bg-surface-2")}>
                        <td className="max-w-0 px-4 py-2.5">
                          <Link
                            to={`?doc=${encodeURIComponent(doc.document)}`}
                            aria-current={active ? "true" : undefined}
                            className="group flex items-center gap-3 rounded-sm"
                          >
                            <Glyph size={20} aria-label={format.label} className="shrink-0 text-ink-3" />
                            <span className="min-w-0">
                              <span className="block truncate font-medium text-ink group-hover:underline group-hover:underline-offset-4">
                                {doc.titre}
                              </span>
                              <span className="block truncate text-xs text-ink-3">
                                <Mono>{doc.document}</Mono>
                              </span>
                            </span>
                          </Link>
                        </td>
                        <td className="hidden px-3 py-2.5 align-middle sm:table-cell">
                          {doc.statut === "obsolete" ? (
                            <Badge tone="warn">Obsolète</Badge>
                          ) : (
                            <span className="block truncate text-ink-2" title={doc.version ?? undefined}>{doc.version}</span>
                          )}
                        </td>
                        <td className="px-4 py-2.5 text-right">
                          <span className="inline-flex items-center gap-1 tnum text-ink-2">
                            {doc.chunks ?? "—"}
                            <CaretRight size={12} aria-hidden="true" className="text-ink-3" />
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </Card>

            {selected ? (
              <DocumentDetail key={selected.document} doc={selected} />
            ) : (
              <EmptyState title="Choisissez un document.">
                Vous verrez ses métadonnées, sa source réelle et la façon dont il a été découpé : chaque chunk garde le
                chemin de sa section et sa page, pour que l'assistant puisse citer précisément.
              </EmptyState>
            )}
          </div>
        </>
      )}
    </>
  );
}

function DocumentDetail({ doc }: { doc: DocumentInfo }) {
  const chunks = useApi<ChunkInfo[]>(doc.chunks ? `/api/documents/${encodeURIComponent(doc.document)}/chunks` : null);
  const format = FORMAT[doc.format ?? ""] ?? FORMAT.md;
  return (
    <Card className="min-w-0 self-start">
      <div className="border-b border-line p-5">
        <div className="flex flex-wrap gap-1.5">
          <Badge>{format.label}</Badge>
          {doc.categorie && <Badge>{doc.categorie}</Badge>}
          {doc.statut === "obsolete" ? <Badge tone="warn">Obsolète : exclu de la recherche</Badge> : <Badge tone="good">En vigueur</Badge>}
        </div>
        <h2 className="mt-3 text-xl tracking-[-0.6px]">{doc.titre}</h2>
        <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
          <dt className="text-ink-3">Fichier</dt>
          <dd className="min-w-0 truncate">
            <Mono>{doc.document}</Mono>
          </dd>
          <dt className="text-ink-3">Version</dt>
          <dd>
            {doc.version}
            {doc.date_effet && <span className="text-ink-3"> · en vigueur le {fmt.date(doc.date_effet)}</span>}
          </dd>
          {doc.pages != null && (
            <>
              <dt className="text-ink-3">Pages</dt>
              <dd className="tnum">{doc.pages}</dd>
            </>
          )}
          <dt className="text-ink-3">Indexation</dt>
          <dd className="tnum">
            {doc.chunks ?? "—"} chunks, {fmt.int(doc.tokens)} tokens
          </dd>
        </dl>
        <p className="mt-3 text-[13px] leading-5 text-ink-3">{doc.sources}</p>
      </div>

      <div className="p-5">
        <h3 className="mb-3 text-[15px] tracking-[-0.2px]">Découpage</h3>
        {chunks.error ? (
          <ErrorState error={chunks.error} onRetry={chunks.reload} />
        ) : !chunks.data ? (
          doc.chunks ? (
            <div className="grid grid-cols-1 gap-2">
              <Skeleton className="h-20" />
              <Skeleton className="h-20" />
            </div>
          ) : (
            <p className="text-sm text-ink-3">Index non chargé : lancez l'API avec la recherche activée.</p>
          )
        ) : (
          <ol className="grid grid-cols-1 gap-2">
            {chunks.data.map((chunk) => (
              <ChunkCard key={chunk.index} chunk={chunk} />
            ))}
          </ol>
        )}
      </div>
    </Card>
  );
}

function ChunkCard({ chunk }: { chunk: ChunkInfo }) {
  const [open, setOpen] = useState(false);
  const path = chunk.section?.split(" > ").slice(1).join(" › ");
  const label = path || (chunk.text.includes("### ") ? "Sections courtes regroupées" : "Introduction du document");
  return (
    <li className="rounded-md bg-surface-2 p-3">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 text-xs text-ink-3">
        <span className="min-w-0 truncate font-medium text-ink-2">{label}</span>
        <span className="tnum shrink-0">
          #{chunk.index}
          {chunk.page != null && ` · p. ${chunk.page}`} · {chunk.tokens} tokens
        </span>
      </div>
      <div className={cx("mt-1.5 overflow-hidden", !open && "max-h-[60px] [mask-image:linear-gradient(#000_60%,transparent)]")}>
        <ChunkText text={chunk.text} />
      </div>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="mt-1 text-xs font-medium text-accent-ink underline-offset-4 hover:underline"
      >
        {open ? "Réduire" : "Lire le chunk"}
      </button>
    </li>
  );
}

/** Texte d'un chunk : les tableaux Markdown sont rendus en tableau (jamais coupés à l'indexation),
 *  les sous-titres « ### » ajoutés lors des regroupements en gras. */
function ChunkText({ text }: { text: string }) {
  const blocks: { kind: "text" | "table"; lines: string[] }[] = [];
  for (const line of text.split("\n")) {
    const kind = line.trimStart().startsWith("|") ? "table" : "text";
    const last = blocks.at(-1);
    if (last && last.kind === kind) last.lines.push(line);
    else blocks.push({ kind, lines: [line] });
  }
  return (
    <div className="grid grid-cols-1 gap-2 text-[13px] leading-5 break-words text-ink-2">
      {blocks.map((block, i) => {
        if (block.kind === "table") {
          const rows = block.lines
            .filter((l) => !/^\s*\|?[\s:|-]+\|?\s*$/.test(l))
            .map((l) => l.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim()));
          const [head, ...body] = rows;
          return (
            <div key={i} className="overflow-x-auto rounded-md bg-surface">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-left text-ink-3">
                    {head?.map((cell, j) => (
                      <th key={j} scope="col" className="px-2.5 py-1.5 font-normal">
                        {cell}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {body.map((row, r) => (
                    <tr key={r} className="border-t border-line">
                      {row.map((cell, j) => (
                        <td key={j} className="px-2.5 py-1.5 text-ink-2">
                          {cell}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          );
        }
        return (
          <div key={i} className="grid grid-cols-1 gap-1">
            {block.lines
              .filter((l) => l.trim())
              .map((line, j) =>
                line.startsWith("#") ? (
                  <p key={j} className="font-medium text-ink">
                    {line.replace(/^#+\s*/, "")}
                  </p>
                ) : (
                  <p key={j}>{line.replace(/\*\*/g, "")}</p>
                ),
              )}
          </div>
        );
      })}
    </div>
  );
}