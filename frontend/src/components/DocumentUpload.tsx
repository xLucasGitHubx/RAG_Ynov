import { CheckCircle, UploadSimple, WarningCircle } from "@phosphor-icons/react";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { ApiError, postForm, type UploadResult, type WhoAmI } from "../lib/api";
import { fmt } from "../lib/format";
import { Button, Card, CardHeader, Mono, cx } from "./ui";

const ALL_FORMATS = ".pdf,.docx,.md,.markdown,.txt";
const TEXT_FORMATS = ".md,.markdown,.txt";

const field =
  "h-9 w-full rounded-md bg-surface px-3 text-sm font-normal text-ink shadow-[inset_0_0_0_1px_var(--line-strong)] placeholder:text-ink-3";

type Phase =
  | { kind: "idle" }
  | { kind: "sending"; since: number }
  | { kind: "done"; result: UploadResult; title: string }
  | { kind: "error"; message: string };

/** Titre proposé à partir du nom de fichier : « procedure_vpn-2026.pdf » → « Procedure vpn 2026 ». */
function titleFromFile(name: string): string {
  const stem = name.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ").trim();
  return stem.charAt(0).toUpperCase() + stem.slice(1);
}

function formatSize(bytes: number): string {
  return bytes < 1024 * 1024 ? `${fmt.int(bytes / 1024)} Ko` : `${fmt.dec1(bytes / 1024 / 1024)} Mo`;
}

export function DocumentUpload({ info, onAdded }: { info: WhoAmI; onAdded: (document: string) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [dragging, setDragging] = useState(false);
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });
  const [elapsed, setElapsed] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const formRef = useRef<HTMLFormElement>(null);
  const accept = info.upload.docling ? ALL_FORMATS : TEXT_FORMATS;
  const sending = phase.kind === "sending";

  useEffect(() => {
    if (phase.kind !== "sending") return;
    const id = window.setInterval(() => setElapsed(Math.round((Date.now() - phase.since) / 1000)), 1000);
    return () => window.clearInterval(id);
  }, [phase]);

  const choose = (next: File | null) => {
    setFile(next);
    if (next && !title.trim()) setTitle(titleFromFile(next.name));
    if (phase.kind !== "sending") setPhase({ kind: "idle" });
  };

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!file || sending) return;
    if (file.size > info.upload.max_mb * 1024 * 1024) {
      setPhase({ kind: "error", message: `Fichier trop volumineux : ${info.upload.max_mb} Mo au plus.` });
      return;
    }
    const form = new FormData(event.currentTarget);
    form.set("fichier", file);
    form.set("remplacer", form.get("remplacer") ? "true" : "false");
    setElapsed(0);
    setPhase({ kind: "sending", since: Date.now() });
    try {
      const result = await postForm<UploadResult>("/api/admin/documents", form);
      setPhase({ kind: "done", result, title: title.trim() });
      setFile(null);
      setTitle("");
      formRef.current?.reset();
      onAdded(result.document);
    } catch (err) {
      const message = err instanceof ApiError ? err.message : "Envoi impossible : vérifiez la connexion.";
      setPhase({ kind: "error", message });
    }
  };

  return (
    <Card>
      <CardHeader
        title="Ajouter un document"
        description={
          <>
            Réservé au rôle admin. PDF (y compris scanné : lu par OCR), Word ou Markdown, {info.upload.max_mb} Mo au
            plus. Le document est découpé et indexé aussitôt : l'assistant peut le citer dès la question suivante.
            {info.environment === "production" &&
              " Sur Azure, l'ajout est conservé jusqu'au prochain déploiement (disque du conteneur)."}
          </>
        }
      />
      <form ref={formRef} onSubmit={submit} className="grid grid-cols-1 gap-4 p-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)]">
        <label
          onDragOver={(event) => {
            event.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(event) => {
            event.preventDefault();
            setDragging(false);
            choose(event.dataTransfer.files[0] ?? null);
          }}
          className={cx(
            "flex min-h-40 cursor-pointer flex-col items-center justify-center gap-2 rounded-lg px-4 py-6 text-center",
            "shadow-[inset_0_0_0_1px_var(--line-strong)] transition-colors duration-150 has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-accent",
            dragging ? "bg-accent-soft" : "bg-surface-2 hover:bg-surface",
          )}
        >
          <UploadSimple size={24} aria-hidden="true" className="text-ink-3" />
          {file ? (
            <span className="min-w-0 max-w-full">
              <Mono className="block truncate text-ink">{file.name}</Mono>
              <span className="text-xs text-ink-3">{formatSize(file.size)} · cliquer pour changer</span>
            </span>
          ) : (
            <span className="text-sm text-ink-2">
              Déposez un fichier ici ou <span className="font-medium text-accent-ink underline underline-offset-4">parcourez</span>
              <span className="mt-1 block text-xs text-ink-3">
                {info.upload.docling ? "PDF, PDF scanné, Word (.docx), Markdown" : "Markdown uniquement (Docling absent)"}
              </span>
            </span>
          )}
          <input
            ref={inputRef}
            type="file"
            name="fichier-choisi"
            accept={accept}
            className="sr-only"
            onChange={(event) => choose(event.target.files?.[0] ?? null)}
          />
        </label>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <label className="grid grid-cols-1 gap-1.5 text-sm font-medium sm:col-span-2">
            Titre
            <input
              name="titre"
              required
              minLength={3}
              maxLength={200}
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder="Procédure d'accès au VPN…"
              autoComplete="off"
              className={field}
            />
          </label>
          <label className="grid grid-cols-1 gap-1.5 text-sm font-medium">
            Catégorie
            <select name="categorie" defaultValue="RH" className={field}>
              <option value="RH">RH</option>
              <option value="IT">IT</option>
              <option value="Autre">Autre</option>
            </select>
          </label>
          <label className="grid grid-cols-1 gap-1.5 text-sm font-medium">
            Statut
            <select name="statut" defaultValue="en_vigueur" className={field}>
              <option value="en_vigueur">En vigueur</option>
              <option value="obsolete">Obsolète (exclu de la recherche)</option>
            </select>
          </label>
          <label className="grid grid-cols-1 gap-1.5 text-sm font-medium">
            Version <span className="sr-only">(facultatif)</span>
            <input name="version" maxLength={40} placeholder="2026" autoComplete="off" className={field} />
          </label>
          <label className="grid grid-cols-1 gap-1.5 text-sm font-medium">
            Date d'effet <span className="sr-only">(facultatif)</span>
            <input name="date_effet" type="date" className={field} />
          </label>
          <label className="flex items-center gap-2 text-sm text-ink-2 sm:col-span-2">
            <input name="remplacer" type="checkbox" className="size-4 accent-[var(--accent)]" />
            Remplacer un document déjà ajouté sous le même nom
          </label>
          <div className="flex flex-wrap items-center gap-3 sm:col-span-2">
            <Button variant="primary" type="submit" disabled={!file || !title.trim() || sending}>
              {sending ? "Indexation…" : "Ajouter et indexer"}
            </Button>
            <p role="status" aria-live="polite" className="min-w-0 flex-1 text-[13px]">
              {phase.kind === "sending" && (
                <span className="text-ink-2">
                  Indexation en cours, <span className="tnum">{elapsed} s</span>. Lecture, découpage puis embeddings ;
                  un scan lu par OCR peut prendre une à deux minutes.
                </span>
              )}
              {phase.kind === "done" && (
                <span className="inline-flex items-start gap-1.5 text-ink-2">
                  <CheckCircle size={16} weight="fill" aria-hidden="true" className="mt-0.5 shrink-0 text-good" />
                  <span>
                    « {phase.title} » indexé : {phase.result.chunks} chunks en {fmt.dec1(phase.result.seconds)} s
                    {phase.result.format === "pdf_scan" && ", texte lu par OCR"}.
                  </span>
                </span>
              )}
              {phase.kind === "error" && (
                <span className="inline-flex items-start gap-1.5 text-bad-ink">
                  <WarningCircle size={16} weight="fill" aria-hidden="true" className="mt-0.5 shrink-0" />
                  <span>{phase.message}</span>
                </span>
              )}
            </p>
          </div>
        </div>
      </form>
    </Card>
  );
}
