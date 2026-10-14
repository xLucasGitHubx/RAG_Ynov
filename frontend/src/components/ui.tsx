import {
  CheckCircle,
  MinusCircle,
  WarningCircle,
  XCircle,
  type Icon,
} from "@phosphor-icons/react";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import { Link, useSearchParams } from "react-router";

export function cx(...classes: (string | false | null | undefined)[]): string {
  return classes.filter(Boolean).join(" ");
}

// ---------------------------------------------------------------- boutons

type Variant = "primary" | "secondary" | "ghost";

export function Button({
  variant = "secondary",
  size = "md",
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: "sm" | "md" }) {
  return (
    <button
      type="button"
      {...props}
      className={cx(
        "inline-flex shrink-0 items-center justify-center gap-2 rounded-md font-medium whitespace-nowrap",
        "transition-[background-color,color,box-shadow,transform] duration-150 active:scale-[0.98]",
        "disabled:pointer-events-none disabled:opacity-50",
        size === "sm" ? "h-8 px-3 text-[13px]" : "h-9 px-3.5 text-sm",
        variant === "primary" && "bg-ink text-bg hover:bg-ink/85",
        variant === "secondary" &&
          "bg-surface text-ink shadow-[inset_0_0_0_1px_var(--line-strong)] hover:bg-surface-2",
        variant === "ghost" && "text-ink-2 hover:bg-surface-2 hover:text-ink",
        className,
      )}
    />
  );
}

export function IconButton({
  label,
  children,
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { label: string; children: ReactNode }) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      {...props}
      className={cx(
        "inline-flex size-8 shrink-0 items-center justify-center rounded-md text-ink-2",
        "transition-[background-color,color] duration-150 hover:bg-surface-2 hover:text-ink",
        "disabled:pointer-events-none disabled:opacity-50",
        className,
      )}
    >
      {children}
    </button>
  );
}

// ---------------------------------------------------------------- surfaces

export function Card({
  children,
  className,
  as: Tag = "section",
  ...rest
}: {
  children: ReactNode;
  className?: string;
  as?: "section" | "div" | "article";
} & React.HTMLAttributes<HTMLElement>) {
  return (
    <Tag
      {...rest}
      className={cx("rounded-lg bg-surface shadow-[inset_0_0_0_1px_var(--line)]", className)}
    >
      {children}
    </Tag>
  );
}

export function CardHeader({
  title,
  description,
  action,
  id,
}: {
  title: string;
  description?: ReactNode;
  action?: ReactNode;
  id?: string;
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3 px-5 pt-5">
      <div className="min-w-0">
        <h3 id={id} className="text-[15px] tracking-[-0.2px]">
          {title}
        </h3>
        {description && <p className="mt-1 max-w-[70ch] text-sm text-ink-3">{description}</p>}
      </div>
      {action}
    </div>
  );
}

export function PageHeader({
  title,
  description,
  action,
}: {
  title: string;
  description?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-4 pb-6">
      <div className="min-w-0">
        <h1 className="text-[28px] leading-9 tracking-[-1.1px] sm:text-[32px] sm:leading-10 sm:tracking-[-1.28px]">
          {title}
        </h1>
        {description && <p className="mt-2 max-w-[68ch] text-[15px] text-ink-2">{description}</p>}
      </div>
      {action}
    </header>
  );
}

export function SectionTitle({ id, children, hint }: { id?: string; children: ReactNode; hint?: ReactNode }) {
  return (
    <div className="mt-10 mb-4 flex flex-wrap items-baseline justify-between gap-2">
      <h2 id={id} className="text-xl tracking-[-0.6px]">
        {children}
      </h2>
      {hint && <p className="text-sm text-ink-3">{hint}</p>}
    </div>
  );
}

// ---------------------------------------------------------------- étiquettes et statuts

type Tone = "neutral" | "accent" | "good" | "bad" | "warn";

const toneClass: Record<Tone, string> = {
  neutral: "bg-surface-2 text-ink-2",
  accent: "bg-accent-soft text-accent-ink",
  good: "bg-good-soft text-good-ink",
  bad: "bg-bad-soft text-bad-ink",
  warn: "bg-warn-soft text-warn-ink",
};

export function Badge({ tone = "neutral", children, className }: { tone?: Tone; children: ReactNode; className?: string }) {
  return (
    <span
      className={cx(
        "inline-flex h-[22px] shrink-0 items-center gap-1 rounded-full px-2 text-xs font-medium whitespace-nowrap",
        toneClass[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

const statusIcon: Record<string, { icon: Icon; className: string; label: string }> = {
  ok: { icon: CheckCircle, className: "text-good", label: "Réussi" },
  passed: { icon: CheckCircle, className: "text-good", label: "Réussi" },
  ko: { icon: XCircle, className: "text-bad", label: "Échec" },
  failed: { icon: XCircle, className: "text-bad", label: "Échec" },
  erreur: { icon: WarningCircle, className: "text-warn", label: "Non évalué" },
  skipped: { icon: MinusCircle, className: "text-ink-3", label: "Ignoré" },
};

/** Un statut n'est jamais porté par la couleur seule : icône + libellé (visible ou lu). */
export function StatusIcon({ status, showLabel = false }: { status: string; showLabel?: boolean }) {
  const meta = statusIcon[status] ?? statusIcon.skipped;
  const Glyph = meta.icon;
  return (
    <span className="inline-flex items-center gap-1.5">
      <Glyph weight="fill" size={16} className={meta.className} aria-hidden="true" />
      {showLabel ? <span className="text-sm text-ink-2">{meta.label}</span> : <span className="sr-only">{meta.label}</span>}
    </span>
  );
}

// ---------------------------------------------------------------- chiffres

export function StatTile({
  label,
  value,
  detail,
  emphasis = false,
}: {
  label: string;
  value: ReactNode;
  detail?: ReactNode;
  emphasis?: boolean;
}) {
  return (
    <Card as="div" className="flex min-w-0 flex-col gap-1 p-5">
      <span className="text-[13px] text-ink-3">{label}</span>
      <span
        className={cx(
          "font-semibold text-ink",
          emphasis ? "text-[40px] leading-[44px] tracking-[-1.8px]" : "text-[28px] leading-9 tracking-[-1px]",
        )}
      >
        {value}
      </span>
      {detail && <span className="text-[13px] text-ink-2">{detail}</span>}
    </Card>
  );
}

/** Jauge horizontale : fond d'un palier plus clair, remplissage de la couleur d'accent. */
export function Meter({ value, label }: { value: number; label: string }) {
  const clamped = Math.max(0, Math.min(1, value));
  return (
    <div
      role="meter"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(clamped * 100)}
      className="h-1.5 w-full overflow-hidden rounded-full bg-accent-soft"
    >
      <div className="h-full rounded-full bg-accent" style={{ width: `${clamped * 100}%` }} />
    </div>
  );
}

// ---------------------------------------------------------------- navigation par onglets

/** Onglets reliés à l'URL (?tab=...) : l'état est partageable et survit au rechargement. */
export function QueryTabs({
  tabs,
  param = "tab",
  label,
}: {
  tabs: { id: string; label: string }[];
  param?: string;
  label: string;
}) {
  const [params] = useSearchParams();
  const current = params.get(param) ?? tabs[0].id;
  return (
    <nav aria-label={label} className="-mx-1 mb-6 overflow-x-auto px-1">
      <ul className="flex min-w-max gap-1 border-b border-line">
        {tabs.map((tab) => {
          const next = new URLSearchParams(params);
          next.set(param, tab.id);
          const active = tab.id === current;
          return (
            <li key={tab.id}>
              <Link
                to={`?${next.toString()}`}
                aria-current={active ? "page" : undefined}
                className={cx(
                  "relative inline-flex h-10 items-center px-3 text-sm transition-colors duration-150",
                  active ? "font-medium text-ink" : "text-ink-3 hover:text-ink",
                )}
              >
                {tab.label}
                {active && <span aria-hidden="true" className="absolute inset-x-3 -bottom-px h-0.5 rounded-full bg-ink" />}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

export function SegmentedControl<T extends string>({
  value,
  onChange,
  options,
  label,
}: {
  value: T;
  onChange: (value: T) => void;
  options: { value: T; label: string }[];
  label: string;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex max-w-full overflow-x-auto rounded-md bg-surface-2 p-0.5 scroll-thin">
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          role="radio"
          aria-checked={option.value === value}
          onClick={() => onChange(option.value)}
          className={cx(
            "h-7 shrink-0 rounded-[5px] px-3 text-[13px] whitespace-nowrap transition-[background-color,color,box-shadow] duration-150",
            option.value === value
              ? "bg-surface font-medium text-ink shadow-[0_0_0_1px_var(--line),0_1px_2px_#0000000f]"
              : "text-ink-3 hover:text-ink",
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------- états

export function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-start gap-2 rounded-lg bg-surface-2 px-6 py-8">
      <p className="font-medium text-ink">{title}</p>
      {children && <div className="max-w-[60ch] text-sm text-ink-2">{children}</div>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden="true" className={cx("pulse-dot rounded-md bg-surface-2", className)} />;
}

export function LoadingBlock({ label = "Chargement…" }: { label?: string }) {
  return (
    <div role="status" className="grid grid-cols-1 gap-3">
      <span className="sr-only">{label}</span>
      <Skeleton className="h-24" />
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Skeleton className="h-28" />
        <Skeleton className="h-28" />
        <Skeleton className="h-28" />
      </div>
      <Skeleton className="h-64" />
    </div>
  );
}

export function CodeLine({ children }: { children: string }) {
  return (
    <code className="block overflow-x-auto rounded-md bg-surface-2 px-3 py-2 font-mono text-[13px] whitespace-pre text-ink-2">
      {children}
    </code>
  );
}

export function Mono({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <span translate="no" className={cx("font-mono text-[12.5px]", className)}>
      {children}
    </span>
  );
}
