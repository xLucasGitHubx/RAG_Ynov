import {
  ArrowDown,
  ArrowRight,
  ArrowSquareOut,
  Browser,
  Cloud,
  Cpu,
  GitBranch,
  GraphicsCard,
  Package,
  type Icon,
} from "@phosphor-icons/react";
import type { ReactNode } from "react";
import { Link } from "react-router";
import { Pipeline } from "../components/Pipeline";
import { Badge, Card, CodeLine, Mono, PageHeader, StatTile, cx } from "../components/ui";
import type { Report } from "../lib/api";
import { fmt } from "../lib/format";
import { useApi } from "../lib/hooks";

const REPO = "https://github.com/xLucasGitHubx/RAG_Ynov";

const SECTIONS = [
  { id: "en-bref", label: "En bref" },
  { id: "parcours", label: "Comment lire ce site" },
  { id: "demarche", label: "La démarche, dans l'ordre" },
  { id: "architecture", label: "Architecture" },
  { id: "choix", label: "Les choix et leurs mesures" },
  { id: "limites", label: "Limites et suites" },
  { id: "reproduire", label: "Reproduire" },
];

function Section({ id, title, intro, children }: { id: string; title: string; intro?: ReactNode; children: ReactNode }) {
  return (
    <section id={id} aria-labelledby={`${id}-titre`} className="scroll-mt-24 pt-12 first:pt-0">
      <h2 id={`${id}-titre`} className="text-xl tracking-[-0.6px]">
        {title}
      </h2>
      {intro && <p className="mt-2 max-w-[70ch] text-[15px] text-ink-2">{intro}</p>}
      <div className="mt-5">{children}</div>
    </section>
  );
}

function SeeLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link to={to} className="inline-flex items-center gap-1 text-sm font-medium text-accent-ink underline-offset-4 hover:underline">
      {children}
      <ArrowRight size={14} aria-hidden="true" />
    </Link>
  );
}

// ================================================================== choix

type Figures = Record<"mrr" | "mrrVector" | "accuracy" | "localAccuracy" | "gpuSeconds" | "nf4Vram", string>;

const CHOICES = (f: Figures): [string, string, string, string][] => [
  ["Taille des chunks", "256 tokens", "384 à 1 024 tokens, par article", "À moins de 2 points du meilleur recall@5, avec 26 % de tokens en moins envoyés au modèle"],
  ["Recherche", "Hybride BM25 + vecteurs", "Vecteurs seuls", `MRR ${f.mrr} contre ${f.mrrVector} : les échecs restants étaient des mots exacts`],
  ["Reranker", "Aucun", "bge-reranker-v2-m3, mMiniLM", "15 s puis 1,3 s par question sur CPU, pour un gain nul ou faible"],
  ["Hors périmètre", "Seuil cosinus 0,42", "Toujours appeler le modèle", "3 questions sur 10 refusées sans GPU, aucune question légitime perdue"],
  ["Modèle", "Ministral 3 8B bf16", "Ministral 3 3B (local)", `${f.accuracy} de réponses correctes contre ${f.localAccuracy}, ${f.gpuSeconds} de GPU par réponse`],
  ["Quantization", "bf16 sur ZeroGPU ; nf4 pour un GPU dédié", "int8", `nf4 tient dans ${f.nf4Vram} sans perte mesurée ; int8 est 5 fois plus lent`],
  ["Interface", "React servie par l'API", "Gradio (prévu au plan)", "Une seule image Docker, design et accessibilité maîtrisés ; Gradio reste pour le Space"],
];

// ================================================================== page

export function ProjectPage() {
  const report = useApi<Report>("/api/reports");
  const r = report.data;
  const runs = r?.answers.runs ?? [];
  const prod = runs.find((run) => run.version === "zerogpu");
  const local = runs.find((run) => run.version === "v3");
  const hybrid = r?.retrieval.comparison.find((c) => c.key === "hybrid");
  const vector = r?.retrieval.comparison.find((c) => c.key === "vector");
  const nf4 = r?.quantization.find((q) => q.model.includes("nf4"));

  const figures = {
    accuracy: prod ? fmt.pct(prod.summary.accuracy) : "97 %",
    accuracyDetail: prod ? `${prod.summary.correct} sur ${prod.summary.evaluated}` : "56 sur 58",
    localAccuracy: local ? fmt.pct(local.summary.accuracy) : "91 %",
    r5: hybrid ? fmt.pct(hybrid.recall_at_5) : "98 %",
    mrr: hybrid ? fmt.dec2(hybrid.mrr_at_10) : "0,94",
    mrrVector: vector ? fmt.dec2(vector.mrr_at_10) : "—",
    gpuSeconds: prod?.summary.generation_seconds_p50 != null ? `${fmt.dec1(prod.summary.generation_seconds_p50)} s` : "1,5 s",
    pii: r ? `${r.security.blocked}/${r.security.messages.length}` : "20/20",
    falsePositives: r ? `${r.security.false_positives} faux positif sur ${fmt.int(r.security.legit_questions)} questions` : "",
    tests: r?.tests ? `${r.tests.passed}/${r.tests.total}` : "—",
    oos: prod ? `${prod.summary.oos_refused}/${prod.summary.oos_total}` : "10/10",
    nf4Vram: nf4?.vram_gb != null ? `${fmt.dec1(nf4.vram_gb)} Go` : "6,7 Go",
  };

  return (
    <>
      <PageHeader
        title="Le projet."
        description="Ce que fait l'assistant, comment il a été construit étape par étape, et où vérifier chaque affirmation sur ce site. Cette page se lit de haut en bas, sans connaissance préalable du projet."
      />

      <div className="grid grid-cols-1 gap-10 xl:grid-cols-[minmax(0,1fr)_200px]">
        <div className="min-w-0">
          {/* ------------------------------------------------------------ en bref */}
          <Section id="en-bref" title="En bref.">
            <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
              {[
                {
                  title: "Le besoin",
                  text: "Les salariés d'une ESN se posent les mêmes questions : congés, télétravail, mutuelle, notes de frais, VPN. Les réponses sont dans une dizaine de documents internes que personne ne lit en entier.",
                },
                {
                  title: "La solution",
                  text: "Un assistant RAG : il retrouve les passages utiles dans les documents, puis un modèle de langage rédige la réponse à partir de ces seuls passages, en citant document, section et page. Hors du périmètre, il le dit.",
                },
                {
                  title: "Les contraintes",
                  text: "Un modèle open-weight auto-hébergé (aucune API propriétaire), une API en Docker sur le cloud, un GPU gratuit mais limité (ZeroGPU de Hugging Face) et des questions qui peuvent contenir des données personnelles (RGPD).",
                },
              ].map((block) => (
                <Card key={block.title} as="div" className="p-5">
                  <h3 className="text-[15px] tracking-[-0.2px]">{block.title}</h3>
                  <p className="mt-2 text-sm text-ink-2">{block.text}</p>
                </Card>
              ))}
            </div>
            <p className="mt-4 max-w-[70ch] text-sm text-ink-3">
              L'entreprise, Nexalis Conseil, est fictive ; chacune de ses règles s'appuie sur une source publique citée
              (Légifrance, service-public.fr, convention Syntec). Les montants propres à Nexalis sont inventés.
            </p>
            <div className="mt-6 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <StatTile label="Réponses correctes" value={figures.accuracy} detail={`${figures.accuracyDetail}, Ministral 3 8B`} />
              <StatTile label="Bonne source dans le top 5" value={figures.r5} detail={`Recherche hybride, MRR ${figures.mrr}`} />
              <StatTile label="Données personnelles bloquées" value={figures.pii} detail={figures.falsePositives} />
              <StatTile label="Tests automatisés" value={figures.tests} detail="Relancés à chaque modification" />
            </div>
          </Section>

          {/* ------------------------------------------------------------ parcours */}
          <Section
            id="parcours"
            title="Comment lire ce site."
            intro="Chaque page répond à une question précise. Sur la version publique, une clé d'API est demandée : bouton clé, en bas du menu."
          >
            <Card className="overflow-hidden">
              <ul>
                {[
                  { to: "/", label: "Vue d'ensemble", text: "Les chiffres clés, le trajet d'une question et la configuration en service, lue en direct sur l'API." },
                  { to: "/assistant", label: "Assistant", text: "L'essayer. Les citations renvoient aux extraits utilisés. Essayez aussi une question hors sujet, ou un message avec un numéro de téléphone : il est bloqué avant toute recherche." },
                  { to: "/corpus", label: "Corpus", text: "Les documents, leur source réelle et leur découpage en chunks. Avec une clé admin, on peut y ajouter un document (PDF, scan, Word, Markdown)." },
                  { to: "/evaluation", label: "Évaluation", text: "La preuve de chaque choix : taille des chunks, recherche hybride, seuil de refus, prompt, modèle et quantization, sécurité. Chaque question évaluée est consultable." },
                  { to: "/tests", label: "Tests", text: "Les tests automatisés, fichier par fichier, sans réseau ni modèle chargé." },
                  { to: "/monitoring", label: "Monitoring", text: "Chaque question posée devient une mesure MLflow : durée de chaque étape, refus, feedback. Jamais le texte de la question." },
                ].map((item) => (
                  <li key={item.to} className="grid grid-cols-1 gap-1 border-b border-line px-5 py-3.5 last:border-b-0 sm:grid-cols-[160px_minmax(0,1fr)] sm:gap-4">
                    <Link to={item.to} className="text-sm font-medium text-ink underline-offset-4 hover:underline">
                      {item.label}
                    </Link>
                    <p className="text-sm text-ink-2">{item.text}</p>
                  </li>
                ))}
                <li className="grid grid-cols-1 gap-1 px-5 py-3.5 sm:grid-cols-[160px_minmax(0,1fr)] sm:gap-4">
                  <a href="/docs" className="text-sm font-medium text-ink underline-offset-4 hover:underline">
                    Swagger
                  </a>
                  <p className="text-sm text-ink-2">L'API brute, testable route par route.</p>
                </li>
              </ul>
            </Card>
          </Section>

          {/* ------------------------------------------------------------ démarche */}
          <Section
            id="demarche"
            title="La démarche, dans l'ordre."
            intro="Le projet suit un plan en 9 itérations. Chacune avait un critère de fin vérifiable ; aucun réglage n'a été choisi sans mesure."
          >
            <ol className="grid grid-cols-1 gap-3">
              {[
                {
                  title: "Le squelette",
                  goal: "Une API qui répond.",
                  done: "FastAPI avec POST /ask et GET /health, schémas Pydantic, documentation Swagger.",
                  result: "L'API répond et se teste depuis /docs.",
                  link: { to: "/tests", label: "Tests" },
                },
                {
                  title: "La conteneurisation",
                  goal: "Lancer le projet sans rien installer d'autre que Docker.",
                  done: "Dockerfile multi-étapes (interface, dépendances, modèles, image finale), utilisateur non root, contrôle de santé ; docker-compose avec l'API, Ollama et MLflow.",
                  result: "Les modèles sont dans l'image : aucun téléchargement au démarrage. Trois bugs trouvés en construisant l'image pour de vrai, puis corrigés.",
                },
                {
                  title: "La mémoire",
                  goal: "Retrouver le bon passage.",
                  done: "Corpus de 21 documents en 4 formats (dont deux scans lus par OCR) : 10 documents internes et 11 fiches de la convention Syntec à jour de 2026, rédigées à partir de Légifrance. Ingestion Docling idempotente, découpage par titres puis par taille, tableaux jamais coupés, embeddings BGE-M3, base ChromaDB.",
                  result: "16 configurations mesurées sur les 100 questions publiques Syntec : 256 tokens retenu, à moins de 2 points du meilleur score avec 26 % de tokens en moins envoyés au modèle.",
                  link: { to: "/evaluation?tab=retrieval", label: "Évaluation de la recherche" },
                },
                {
                  title: "Le cerveau",
                  goal: "Des réponses justes, sourcées, et un refus propre.",
                  done: "Recherche hybride (BM25 + vecteurs) après avoir constaté que les échecs étaient des mots exacts, seuil de pertinence qui refuse sans appeler le modèle, prompt protégé contre l'injection, réponse en streaming, interface web. Qualité des réponses notée deux fois : par mots-clés et par un LLM juge.",
                  result: `Bonne source dans le top 5 : ${figures.r5} (MRR ${figures.mrr}, contre ${figures.mrrVector} en vecteurs seuls). Réponses correctes : ${figures.localAccuracy} avec le 3B local, ${figures.accuracy} avec le 8B de production.`,
                  link: { to: "/evaluation?tab=reponses", label: "Évaluation des réponses" },
                },
                {
                  title: "Le déploiement cloud",
                  goal: "Une adresse publique, protégée.",
                  done: "Le modèle tourne sur un Space Hugging Face ZeroGPU ; l'API, l'interface et l'index sur Azure Container Apps (Allemagne de l'Ouest, région de l'UE). GitHub Actions teste chaque modification, puis construit l'image et la déploie à chaque fusion sur main.",
                  result: "Mise en ligne sans action manuelle, clés d'API obligatoires. En production, 2,2 s par question côté API, dont 2,0 s de génération : la recherche tient en moins de 0,2 s sur CPU.",
                },
                {
                  title: "L'optimisation",
                  goal: "Le meilleur compromis entre qualité, vitesse et coût.",
                  done: "Rerankers mesurés sur CPU ; quantization comparée en local (GGUF) et sur ZeroGPU (bf16, int8, nf4).",
                  result: `Le reranker prévu (15 s par question sur CPU) est écarté. En nf4, le modèle tient dans ${figures.nf4Vram} sans perte mesurée ; int8 est 5 fois plus lent. bf16 reste retenu sur ZeroGPU.`,
                  link: { to: "/evaluation?tab=modele", label: "Évaluation du modèle" },
                },
                {
                  title: "La sécurité et le RGPD",
                  goal: "Aucune donnée personnelle ne passe, aucun abus.",
                  done: "Filtre d'entrée (numéro de sécurité sociale avec clé, IBAN, carte bancaire, e-mail, téléphone), clés d'API à deux rôles, limite de débit, journaux sans contenu de question, garde-fous contre l'injection, note RGPD.",
                  result: `${figures.pii} messages piégés bloqués, ${figures.falsePositives || "aucun faux positif"}.`,
                  link: { to: "/evaluation?tab=securite", label: "Évaluation de la sécurité" },
                },
                {
                  title: "MLOps avec MLflow",
                  goal: "Savoir ce qui se passe en production et comparer les essais.",
                  done: "Chaque question devient une mesure MLflow (latence par étape, scores, tokens, feedback) ; chaque évaluation aussi ; la configuration retenue est enregistrée au registre de modèles.",
                  result: "Le monitoring de ce site se lit en direct.",
                  link: { to: "/monitoring", label: "Monitoring" },
                },
                {
                  title: "FinOps et documentation",
                  goal: "Savoir ce que coûterait le service et le rendre compréhensible.",
                  done: `Budget pour 1 000 utilisateurs par jour à partir du temps GPU mesuré (${figures.gpuSeconds} par réponse) et coût d'usage des LLM en euros, par réponse et par mois (onglet Coûts), README, résultats détaillés, note RGPD, guide de déploiement, et cette page.`,
                  result: "Environ 122 $ par mois avec ZeroGPU, 223 $ avec un GPU L4 dédié, qui reste le choix recommandé pour une vraie production.",
                },
              ].map((step, index) => (
                <li key={step.title}>
                  <Card as="article" className="grid grid-cols-1 gap-3 p-5 sm:grid-cols-[44px_minmax(0,1fr)]">
                    <span aria-hidden="true" className="flex size-9 items-center justify-center rounded-full bg-surface-2 text-sm font-semibold tnum text-ink">
                      {index + 1}
                    </span>
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <h3 className="text-[15px] tracking-[-0.2px]">
                          <span className="sr-only">Itération {index + 1} : </span>
                          {step.title}
                        </h3>
                        <Badge tone="good">Fait</Badge>
                      </div>
                      <dl className="mt-2 grid grid-cols-1 gap-1.5 text-sm sm:grid-cols-[110px_minmax(0,1fr)] sm:gap-x-4">
                        <dt className="text-ink-3">Objectif</dt>
                        <dd className="text-ink-2">{step.goal}</dd>
                        <dt className="text-ink-3">Réalisé</dt>
                        <dd className="text-ink-2">{step.done}</dd>
                        <dt className="text-ink-3">Résultat</dt>
                        <dd className="text-ink">{step.result}</dd>
                      </dl>
                      {step.link && (
                        <div className="mt-3">
                          <SeeLink to={step.link.to}>{step.link.label}</SeeLink>
                        </div>
                      )}
                    </div>
                  </Card>
                </li>
              ))}
            </ol>
          </Section>

          {/* ------------------------------------------------------------ architecture */}
          <Section
            id="architecture"
            title="Architecture."
            intro="Tout ce qui n'a pas besoin de GPU tourne sur CPU, dans l'API. Le GPU ne sert qu'à rédiger la réponse : c'est le poste qui coûte, donc le seul qui est externalisé."
          >
            <h3 className="mb-3 text-[15px] tracking-[-0.2px]">Le trajet d'une question</h3>
            <Pipeline />
            <h3 className="mt-8 mb-3 text-[15px] tracking-[-0.2px]">Où tourne quoi</h3>
            <Deployment />
          </Section>

          {/* ------------------------------------------------------------ choix */}
          <Section
            id="choix"
            title="Les choix et leurs mesures."
            intro="Les décisions qui ont le plus pesé, ce qui a été écarté, et le chiffre qui a tranché."
          >
<Card className="overflow-hidden">
              <div
                aria-hidden="true"
                className="hidden grid-cols-[140px_minmax(0,1fr)_minmax(0,1fr)_minmax(0,1.4fr)] gap-4 bg-surface-2 px-5 py-2.5 text-[13px] text-ink-3 md:grid"
              >
                <span>Sujet</span>
                <span>Retenu</span>
                <span>Écarté</span>
                <span>Ce qui a tranché</span>
              </div>
              <ul aria-label="Choix techniques, alternatives écartées et mesures">
                {CHOICES(figures).map(([topic, kept, dropped, why]) => (
                  <li
                    key={topic}
                    className="grid grid-cols-1 gap-1 border-t border-line px-5 py-3 text-sm first:border-t-0 md:grid-cols-[140px_minmax(0,1fr)_minmax(0,1fr)_minmax(0,1.4fr)] md:gap-4 md:first:border-t"
                  >
                    <span className="font-medium text-ink">{topic}</span>
                    <span className="text-ink">
                      <span className="text-ink-3 md:sr-only">Retenu : </span>
                      {kept}
                    </span>
                    <span className="text-ink-2">
                      <span className="text-ink-3 md:sr-only">Écarté : </span>
                      {dropped}
                    </span>
                    <span className="text-ink-2">
                      <span className="text-ink-3 md:sr-only">Ce qui a tranché : </span>
                      {why}
                    </span>
                  </li>
                ))}
              </ul>
            </Card>
          </Section>

          {/* ------------------------------------------------------------ limites */}
          <Section id="limites" title="Limites et suites." intro="Ce qui ne marche pas encore parfaitement, dit franchement.">
            <ul className="grid grid-cols-1 gap-3 md:grid-cols-2">
              {[
                ["Une erreur de lecture de tableau", "Sur une question Syntec, le modèle lit la ligne des ETAM au lieu de celle des cadres. Piste : découper les tableaux de la convention par catégorie de salarié."],
                ["Des données éphémères sur Azure", "La base MLflow et les documents ajoutés vivent sur le disque du conteneur : ils repartent de zéro à chaque déploiement. Piste : Azure Files ou un serveur MLflow dédié."],
                ["Un GPU partagé", "ZeroGPU met le Space en pause après inactivité et n'offre aucune garantie de disponibilité. Pour une vraie production : un GPU L4 dédié, ou une T4 avec le modèle en nf4."],
                ["Une évaluation par mots-clés", "Les réponses sont jugées sur les chiffres et termes attendus, pas sur la fidélité de chaque phrase. Piste : un juge LLM (RAGAS)."],
                ["Un corpus à revérifier", "Les règles légales du corpus ont été rédigées à partir de sources publiques, à revérifier avant tout usage réel."],
                ["Une seule réplique", "Une instance de l'API suffit pour la démonstration. En charge : file d'attente et serveur d'inférence avec batching (vLLM)."],
              ].map(([title, text]) => (
                <li key={title}>
                  <Card as="div" className="h-full p-5">
                    <h3 className="text-[15px] tracking-[-0.2px]">{title}</h3>
                    <p className="mt-1.5 text-sm text-ink-2">{text}</p>
                  </Card>
                </li>
              ))}
            </ul>
          </Section>

          {/* ------------------------------------------------------------ reproduire */}
          <Section
            id="reproduire"
            title="Reproduire."
            intro="Le dépôt contient tout : code, corpus, jeux de questions, résultats bruts et documentation."
          >
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              <Card className="p-5">
                <h3 className="text-[15px] tracking-[-0.2px]">En local, avec Docker</h3>
                <div className="mt-3 grid grid-cols-1 gap-2">
                  <CodeLine>{`git clone ${REPO}.git`}</CodeLine>
                  <CodeLine>docker compose up --build</CodeLine>
                </div>
                <p className="mt-3 text-sm text-ink-2">
                  Puis <Mono>http://localhost:7860/ui</Mono>. Le modèle local se télécharge une fois avec{" "}
                  <Mono>docker compose exec ollama ollama pull ministral-3:3b</Mono>.
                </p>
              </Card>
              <Card className="p-5">
                <h3 className="text-[15px] tracking-[-0.2px]">Relancer les mesures</h3>
                <div className="mt-3 grid grid-cols-1 gap-2">
                  <CodeLine>pytest</CodeLine>
                  <CodeLine>python -m eval.eval_retrieval --dataset nexalis --hybrid</CodeLine>
                  <CodeLine>python -m eval.eval_answers</CodeLine>
                </div>
              </Card>
            </div>
            <div className="mt-4 flex flex-wrap gap-x-6 gap-y-2">
              <a href={REPO} className="inline-flex items-center gap-1 text-sm font-medium text-accent-ink underline-offset-4 hover:underline">
                Le dépôt GitHub
                <ArrowSquareOut size={14} aria-hidden="true" />
              </a>
              {[
                ["docs/resultats_retrieval.md", "Résultats de la recherche"],
                ["docs/resultats_reponses.md", "Résultats des réponses"],
                ["docs/estimation_budget.md", "Budget"],
                ["docs/note_rgpd.md", "Note RGPD"],
                ["docs/deploiement_azure.md", "Déploiement Azure"],
              ].map(([path, label]) => (
                <a
                  key={path}
                  href={`${REPO}/blob/main/${path}`}
                  className="inline-flex items-center gap-1 text-sm font-medium text-accent-ink underline-offset-4 hover:underline"
                >
                  {label}
                  <ArrowSquareOut size={14} aria-hidden="true" />
                </a>
              ))}
            </div>
          </Section>
        </div>

        {/* ------------------------------------------------------------ sommaire */}
        <nav aria-label="Sommaire de la page" className="hidden xl:block">
          <div className="sticky top-10">
            <p className="mb-2 text-[13px] text-ink-3">Sur cette page</p>
            <ul className="grid grid-cols-1 gap-1 border-l border-line">
              {SECTIONS.map((section) => (
                <li key={section.id}>
                  <a href={`#${section.id}`} className="-ml-px block border-l border-transparent py-1 pl-3 text-sm text-ink-2 hover:border-ink hover:text-ink">
                    {section.label}
                  </a>
                </li>
              ))}
            </ul>
          </div>
        </nav>
      </div>
    </>
  );
}

// ================================================================== schéma de déploiement

function Node({ icon: Glyph, title, place, items, gpu = false }: { icon: Icon; title: string; place: string; items: string[]; gpu?: boolean }) {
  return (
    <div className={cx("min-w-0 rounded-lg p-4", gpu ? "bg-ink text-bg" : "bg-surface shadow-[inset_0_0_0_1px_var(--line)]")}>
      <div className="flex items-center gap-2">
        <Glyph size={18} aria-hidden="true" className={gpu ? "text-bg" : "text-ink-2"} />
        <h4 className={cx("text-sm font-medium", gpu ? "text-bg" : "text-ink")}>{title}</h4>
      </div>
      <p className={cx("mt-0.5 text-xs", gpu ? "text-bg/70" : "text-ink-3")}>{place}</p>
      <ul className={cx("mt-3 grid grid-cols-1 gap-1 text-[13px]", gpu ? "text-bg/85" : "text-ink-2")}>
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

function Arrow() {
  return (
    <span aria-hidden="true" className="flex items-center justify-center text-ink-3">
      <ArrowDown size={16} className="lg:hidden" />
      <ArrowRight size={16} className="hidden lg:block" />
    </span>
  );
}

function Deployment() {
  return (
    <div className="grid grid-cols-1 gap-3">
      <div className="grid grid-cols-1 items-stretch gap-2 lg:grid-cols-[minmax(0,0.8fr)_24px_minmax(0,1.4fr)_24px_minmax(0,1fr)]">
        <Node icon={Browser} title="Navigateur" place="Salarié, évaluateur" items={["Interface React (/ui)", "Clé d'API dans l'en-tête"]} />
        <Arrow />
        <Node
          icon={Cpu}
          title="API FastAPI"
          place="Azure Container Apps · 2 vCPU, 4 Go · Allemagne de l'Ouest"
          items={[
            "Filtre RGPD, clés d'API, limite de débit",
            "BGE-M3, ChromaDB et BM25 : la recherche",
            "Docling : ajout de documents (admin)",
            "MLflow : suivi de chaque question",
          ]}
        />
        <Arrow />
        <Node
          icon={GraphicsCard}
          title="Space ZeroGPU"
          place="Hugging Face · GPU attribué à la demande"
          items={["Ministral 3 8B en bf16", "Un seul prompt par question", "Réponse en streaming"]}
          gpu
        />
      </div>
      <Card as="div" className="flex flex-wrap items-center gap-x-3 gap-y-2 p-4 text-[13px] text-ink-2">
        <span className="inline-flex items-center gap-1.5 font-medium text-ink">
          <GitBranch size={16} aria-hidden="true" />
          Mise en ligne
        </span>
        <span>Fusion sur main</span>
        <ArrowRight size={14} aria-hidden="true" className="text-ink-3" />
        <span>CI : ruff, pytest, build de l'interface</span>
        <ArrowRight size={14} aria-hidden="true" className="text-ink-3" />
        <span className="inline-flex items-center gap-1.5">
          <Package size={14} aria-hidden="true" />
          Image dans Azure Container Registry
        </span>
        <ArrowRight size={14} aria-hidden="true" className="text-ink-3" />
        <span className="inline-flex items-center gap-1.5">
          <Cloud size={14} aria-hidden="true" />
          Nouvelle révision, contrôle de /health
        </span>
      </Card>
    </div>
  );
}
