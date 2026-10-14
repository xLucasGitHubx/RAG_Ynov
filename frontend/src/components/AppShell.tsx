import {
  ChartLineUp,
  ChatCircleText,
  Files,
  Key,
  List,
  Moon,
  Pulse,
  SquaresFour,
  Sun,
  TestTube,
  X,
  type Icon,
} from "@phosphor-icons/react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { NavLink, Outlet, useLocation } from "react-router";
import { getApiKey, setApiKey, type Health } from "../lib/api";
import { fmt } from "../lib/format";
import { useApi, useTheme } from "../lib/hooks";
import { Button, IconButton, cx } from "./ui";

const NAV: { to: string; label: string; icon: Icon; end?: boolean }[] = [
  { to: "/", label: "Vue d'ensemble", icon: SquaresFour, end: true },
  { to: "/assistant", label: "Assistant", icon: ChatCircleText },
  { to: "/corpus", label: "Corpus", icon: Files },
  { to: "/evaluation", label: "Évaluation", icon: ChartLineUp },
  { to: "/tests", label: "Tests", icon: TestTube },
  { to: "/monitoring", label: "Monitoring", icon: Pulse },
];

export const OPEN_KEY_DIALOG = "nexalis-open-key-dialog";

function Wordmark() {
  return (
    <span className="flex items-center gap-2.5">
      <svg width="24" height="24" viewBox="0 0 32 32" aria-hidden="true" className="shrink-0">
        <rect width="32" height="32" rx="7" fill="var(--ink)" />
        <path d="M9 23V9h2.6l7.8 9.6V9H22v14h-2.6l-7.8-9.6V23z" fill="var(--bg)" />
      </svg>
      <span className="leading-tight">
        <span translate="no" className="block text-[15px] font-semibold tracking-[-0.3px] text-ink">
          Nexalis
        </span>
        <span className="block text-xs text-ink-3">Assistant RH et IT</span>
      </span>
    </span>
  );
}

function NavItems({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <ul className="grid grid-cols-1 gap-0.5">
      {NAV.map(({ to, label, icon: Glyph, end }) => (
        <li key={to}>
          <NavLink
            to={to}
            end={end}
            onClick={onNavigate}
            className={({ isActive }) =>
              cx(
                "group relative flex h-9 items-center gap-2.5 rounded-md px-2.5 text-sm transition-[background-color,color] duration-150",
                isActive ? "bg-surface-2 font-medium text-ink" : "text-ink-2 hover:bg-surface-2 hover:text-ink",
              )
            }
          >
            {({ isActive }) => (
              <>
                {isActive && <span aria-hidden="true" className="absolute top-2 bottom-2 -left-3 w-0.5 rounded-full bg-ink" />}
                <Glyph size={18} weight={isActive ? "fill" : "regular"} aria-hidden="true" />
                {label}
              </>
            )}
          </NavLink>
        </li>
      ))}
    </ul>
  );
}

function ServiceStatus() {
  const { data, error } = useApi<Health>("/health", 30000);
  const online = Boolean(data) && !error;
  return (
    <div className="rounded-md bg-surface-2 px-3 py-2.5 text-xs">
      <div className="flex items-center gap-2 text-ink-2">
        <span
          aria-hidden="true"
          className={cx("size-2 rounded-full", online ? "bg-good" : "bg-bad", !data && !error && "pulse-dot bg-ink-3")}
        />
        <span className="font-medium text-ink">{online ? "API en ligne" : error ? "API injoignable" : "Connexion…"}</span>
      </div>
      {data && (
        <dl className="mt-1.5 grid grid-cols-[auto_1fr] gap-x-2 gap-y-0.5 text-ink-3">
          <dt>LLM</dt>
          <dd className="truncate text-right font-mono text-[11.5px] text-ink-2" translate="no" title={data.llm_model}>
            {data.llm_model}
          </dd>
          <dt>Index</dt>
          <dd className="text-right tnum text-ink-2">
            {data.indexed_chunks == null ? "non chargé" : `${fmt.int(data.indexed_chunks)} chunks`}
          </dd>
        </dl>
      )}
    </div>
  );
}

function ShellActions() {
  const [theme, setTheme] = useTheme();
  const [hasKey, setHasKey] = useState(() => Boolean(getApiKey()));
  useEffect(() => {
    const onChange = () => setHasKey(Boolean(getApiKey()));
    window.addEventListener("nexalis-api-key", onChange);
    return () => window.removeEventListener("nexalis-api-key", onChange);
  }, []);
  return (
    <div className="flex items-center gap-1">
      <IconButton
        label={theme === "dark" ? "Passer au thème clair" : "Passer au thème sombre"}
        onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
      >
        {theme === "dark" ? <Sun size={18} aria-hidden="true" /> : <Moon size={18} aria-hidden="true" />}
      </IconButton>
      <IconButton
        label={hasKey ? "Modifier la clé d'API" : "Saisir une clé d'API"}
        onClick={() => window.dispatchEvent(new Event(OPEN_KEY_DIALOG))}
      >
        <Key size={18} weight={hasKey ? "fill" : "regular"} aria-hidden="true" />
      </IconButton>
      <a
        href="/docs"
        className="ml-auto rounded-md px-2 py-1 text-xs text-ink-3 transition-colors duration-150 hover:text-ink"
      >
        Swagger
      </a>
    </div>
  );
}

function ApiKeyDialog() {
  const ref = useRef<HTMLDialogElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    const open = () => {
      ref.current?.showModal();
      if (inputRef.current) inputRef.current.value = getApiKey();
    };
    window.addEventListener(OPEN_KEY_DIALOG, open);
    return () => window.removeEventListener(OPEN_KEY_DIALOG, open);
  }, []);
  return (
    <dialog
      ref={ref}
      aria-labelledby="api-key-title"
      className="m-auto w-[min(440px,calc(100vw-32px))] overscroll-contain rounded-lg bg-surface p-0 text-ink shadow-[var(--overlay-shadow)] backdrop:bg-black/40"
    >
      <form
        method="dialog"
        className="grid grid-cols-1 gap-4 p-6"
        onSubmit={() => setApiKey(inputRef.current?.value.trim() ?? "")}
      >
        <div>
          <h2 id="api-key-title" className="text-lg tracking-[-0.4px]">
            Clé d'API
          </h2>
          <p className="mt-1 text-sm text-ink-2">
            Nécessaire si l'API est lancée avec <code>API_KEYS</code>. La clé reste dans ce navigateur et part dans
            l'en-tête <code>X-API-Key</code>.
          </p>
        </div>
        <label className="grid grid-cols-1 gap-1.5 text-sm font-medium">
          Clé
          <input
            ref={inputRef}
            name="api-key"
            type="password"
            autoComplete="off"
            spellCheck={false}
            placeholder="cle-employe-1…"
            className="h-10 rounded-md bg-surface px-3 font-mono text-sm font-normal shadow-[inset_0_0_0_1px_var(--line-strong)] placeholder:text-ink-3"
          />
        </label>
        <div className="flex justify-end gap-2">
          <Button
            variant="ghost"
            onClick={() => {
              setApiKey("");
              ref.current?.close();
            }}
          >
            Effacer la clé
          </Button>
          <Button variant="primary" type="submit">
            Enregistrer la clé
          </Button>
        </div>
      </form>
    </dialog>
  );
}

function MobileDrawer({ open, onClose, children }: { open: boolean; onClose: () => void; children: ReactNode }) {
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-40 lg:hidden">
      <button type="button" aria-label="Fermer le menu" className="absolute inset-0 bg-black/40" onClick={onClose} />
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Navigation"
        className="absolute inset-y-0 left-0 flex w-[min(300px,85vw)] flex-col gap-6 overflow-y-auto overscroll-contain bg-bg p-4 pt-[max(16px,env(safe-area-inset-top))]"
      >
        {children}
      </div>
    </div>
  );
}

export function AppShell() {
  const [menuOpen, setMenuOpen] = useState(false);
  const location = useLocation();
  useEffect(() => setMenuOpen(false), [location.pathname]);

  const sidebar = (onNavigate?: () => void) => (
    <>
      <div className="flex items-center justify-between px-1">
        <Wordmark />
        {onNavigate && (
          <IconButton label="Fermer le menu" onClick={onNavigate}>
            <X size={18} aria-hidden="true" />
          </IconButton>
        )}
      </div>
      <nav aria-label="Navigation principale" className="px-1">
        <NavItems onNavigate={onNavigate} />
      </nav>
      <div className="mt-auto grid grid-cols-1 gap-3">
        <ServiceStatus />
        <ShellActions />
      </div>
    </>
  );

  return (
    <div className="min-h-dvh lg:grid lg:grid-cols-[248px_minmax(0,1fr)]">
      <a
        href="#contenu"
        className="sr-only z-50 rounded-md bg-ink px-3 py-2 text-sm text-bg focus:not-sr-only focus:fixed focus:top-3 focus:left-3"
      >
        Aller au contenu
      </a>

      <aside className="sticky top-0 hidden h-dvh flex-col gap-6 border-r border-line px-3 py-5 lg:flex">
        {sidebar()}
      </aside>

      <header className="sticky top-0 z-30 flex h-14 items-center justify-between border-b border-line bg-bg px-4 pt-[env(safe-area-inset-top)] lg:hidden">
        <Wordmark />
        <IconButton label="Ouvrir le menu" aria-expanded={menuOpen} onClick={() => setMenuOpen(true)}>
          <List size={20} aria-hidden="true" />
        </IconButton>
      </header>
      <MobileDrawer open={menuOpen} onClose={() => setMenuOpen(false)}>
        {sidebar(() => setMenuOpen(false))}
      </MobileDrawer>

      <main id="contenu" tabIndex={-1} className="min-w-0 px-4 pt-6 pb-16 outline-none sm:px-6 lg:px-10 lg:pt-10">
        <div className="mx-auto w-full max-w-[1200px]">
          <Outlet />
        </div>
      </main>
      <ApiKeyDialog />
    </div>
  );
}
