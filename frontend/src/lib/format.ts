// Formats localisés (Intl) : jamais de format de nombre ou de date codé en dur.

const LOCALE = "fr-FR";

const integer = new Intl.NumberFormat(LOCALE, { maximumFractionDigits: 0 });
const decimal1 = new Intl.NumberFormat(LOCALE, { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const decimal2 = new Intl.NumberFormat(LOCALE, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const decimal3 = new Intl.NumberFormat(LOCALE, { minimumFractionDigits: 3, maximumFractionDigits: 3 });
const percent0 = new Intl.NumberFormat(LOCALE, { style: "percent", maximumFractionDigits: 0 });
const percent1 = new Intl.NumberFormat(LOCALE, { style: "percent", minimumFractionDigits: 1, maximumFractionDigits: 1 });
const euro0 = new Intl.NumberFormat(LOCALE, { style: "currency", currency: "EUR", maximumFractionDigits: 0 });
const euro2 = new Intl.NumberFormat(LOCALE, { style: "currency", currency: "EUR", minimumFractionDigits: 2, maximumFractionDigits: 2 });
const euro4 = new Intl.NumberFormat(LOCALE, { style: "currency", currency: "EUR", minimumFractionDigits: 2, maximumFractionDigits: 4 });
const euroSmall = new Intl.NumberFormat(LOCALE, { style: "currency", currency: "EUR", maximumSignificantDigits: 2 });
const dateTime = new Intl.DateTimeFormat(LOCALE, { dateStyle: "medium", timeStyle: "short" });
const time = new Intl.DateTimeFormat(LOCALE, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
const dateOnly = new Intl.DateTimeFormat(LOCALE, { dateStyle: "long" });

export const fmt = {
  int: (n: number | null | undefined) => (n == null ? "—" : integer.format(n)),
  dec1: (n: number | null | undefined) => (n == null ? "—" : decimal1.format(n)),
  dec2: (n: number | null | undefined) => (n == null ? "—" : decimal2.format(n)),
  dec3: (n: number | null | undefined) => (n == null ? "—" : decimal3.format(n)),
  pct: (n: number | null | undefined) => (n == null ? "—" : percent0.format(n)),
  pct1: (n: number | null | undefined) => (n == null ? "—" : percent1.format(n)),
  /** Euros : 2 décimales, ou 2 chiffres significatifs sous 1 centime (coût d'une réponse). */
  eur: (n: number | null | undefined) =>
    n == null ? "—" : n !== 0 && Math.abs(n) < 0.01 ? euroSmall.format(n) : euro2.format(n),
  eur0: (n: number | null | undefined) => (n == null ? "—" : euro0.format(n)),
  /** Tarif au million de tokens : jusqu'à 4 décimales (0,1275 €). */
  eurPrice: (n: number | null | undefined) => (n == null ? "—" : euro4.format(n)),
  dateTime: (value: string | number | Date) => dateTime.format(new Date(value)),
  time: (value: string | number | Date) => time.format(new Date(value)),
  date: (value: string | number | Date) => dateOnly.format(new Date(value)),
  /** Durée lisible : 6 ms, 840 ms, 1,3 s, 12,6 s. */
  ms: (n: number | null | undefined) => {
    if (n == null) return "—";
    if (n < 1000) return `${integer.format(n)} ms`;
    const seconds = n / 1000;
    const digits = seconds < 100 ? 1 : 0;
    return `${new Intl.NumberFormat(LOCALE, { maximumFractionDigits: digits, minimumFractionDigits: digits }).format(seconds)} s`;
  },
};

/**
 * Typographie française : espace insécable avant « ? ! : ; », à l'intérieur des guillemets
 * et dans les nombres (« 3 000 »), pour qu'aucun signe ne se retrouve seul en début de ligne.
 */
export function fr(text: string): string {
  return text
    .replace(/ ([?!:;»])/g, " $1")
    .replace(/« /g, "« ")
    .replace(/(\d) (\d{3})\b/g, "$1 $2");
}

export function capitalize(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** « test_les_20_messages_faker_sont_detectes » → « Les 20 messages faker sont detectes ». */
export function humanizeTest(name: string): string {
  const base = name.replace(/^test_/, "").replace(/\[.*\]$/, "");
  const parameter = /\[(.*)\]$/.exec(name)?.[1];
  const text = base.replace(/_/g, " ").replace(/\s+/g, " ").trim();
  const sentence = text.charAt(0).toUpperCase() + text.slice(1);
  return parameter ? `${sentence} (${parameter})` : sentence;
}

export const STAGE_LABELS: Record<string, string> = {
  embedding: "Embedding de la question",
  vector_search: "Recherche vectorielle",
  lexical_search: "Recherche BM25",
  rerank: "Reranking",
  llm: "Génération (LLM)",
  total: "Total",
};
