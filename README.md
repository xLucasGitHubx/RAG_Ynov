# Assistant documentaire RH/IT (RAG) — Nexalis Conseil

Projet fil rouge Ynov, module « Industrialisation de l'IA dans le Cloud ».

Un assistant virtuel qui répond aux questions RH et IT des employés (congés, télétravail, mutuelle, pannes) en s'appuyant uniquement sur les documents internes de l'entreprise fictive Nexalis Conseil, avec un LLM open-weight auto-hébergé.

## État d'avancement

| Itération | Sujet | État |
| --- | --- | --- |
| 1 | Squelette : API FastAPI, `/ask`, Swagger | Fait |
| 2 | Conteneurisation : Dockerfile multi-stage | Fait (mis à jour pour le RAG) |
| 3 | Mémoire : corpus, ingestion Docling, chunking mesuré, BGE-M3, ChromaDB | Fait |
| 4 | Cerveau : Ollama local, Space ZeroGPU, recherche hybride, streaming SSE, interface web | Fait |
| 5 | Déploiement : Azure Container Apps + Space ZeroGPU, déploiement continu GitHub Actions | Fait |
| 6 | Optimisation : rerankers, quantization (GGUF local ; bf16 / int8 / nf4 sur ZeroGPU) | Fait |
| 7 | Sécurité et RGPD | Fait |
| 8 | MLOps avec MLflow : runs d'évaluation, suivi par requête, feedback, registre de modèles | Fait |
| 9 | FinOps et documentation | Fait |

Chiffres clés : bonne source dans le top 5 pour 98 % des questions (recherche hybride), **97 % de réponses correctes** (66 / 68) avec Ministral 3 8B bf16 sur ZeroGPU, 10 / 10 questions hors périmètre refusées, 1,5 s de GPU par réponse, ≈ 122 $/mois pour 1 000 utilisateurs par jour (ZeroGPU) ou ≈ 223 $ avec une L4 dédiée.

**En ligne** : https://rag-api.wittysea-7248563d.germanywestcentral.azurecontainerapps.io/ui/ (clé d'API demandée). La page **Le projet** du site raconte la démarche dans l'ordre, pour un lecteur qui découvre le projet.

Résultats détaillés : [docs/resultats_retrieval.md](docs/resultats_retrieval.md) (chunking, recherche hybride, rerankers), [docs/resultats_reponses.md](docs/resultats_reponses.md) (réponses de bout en bout, local et ZeroGPU), [docs/estimation_budget.md](docs/estimation_budget.md) (FinOps), [docs/deploiement_azure.md](docs/deploiement_azure.md) (déploiement). Note RGPD : [docs/note_rgpd.md](docs/note_rgpd.md).

## Architecture

```
Question ──> API FastAPI (CPU)
              ├─ filtre RGPD (NIR, IBAN, carte, e-mail, téléphone) ─> 400 si données perso
              ├─ clé d'API + rôle, limite de débit
              ├─ recherche hybride : BGE-M3 (Chroma) + BM25, fusion RRF, versions obsolètes exclues
              ├─ meilleur score < 0,42 ─> « je ne sais pas » sans appeler le LLM
              ├─ prompt : 5 extraits délimités + règles anti-injection
              └─ LLM : Space ZeroGPU (Ministral 3 8B bf16) ── en développement : Ollama (Ministral 3 3B GGUF)
            ─> réponse + sources (document, section, page) + request_id ─> suivi MLflow
```

Tout ce qui n'a pas besoin de GPU (parsing, embeddings, recherche, sécurité, suivi) tourne sur CPU. Seule la génération utilise le GPU.

## Prérequis

- Python 3.12 ([python.org](https://www.python.org/downloads/))
- Docker Desktop ([docker.com](https://www.docker.com/products/docker-desktop/)) : sert à faire tourner Ollama
- Node.js 22 ([nodejs.org](https://nodejs.org/)) : uniquement pour construire l'interface web
- Git
- ~10 Go d'espace disque (modèles BGE-M3, Docling, Ministral 3B)

## Installation (PowerShell, Windows)

```powershell
# 1. Environnement virtuel
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2. Dépendances (torch en version CPU)
pip install --extra-index-url https://download.pytorch.org/whl/cpu -r requirements-dev.txt

# 3. Configuration
Copy-Item .env.example .env

# 4. LLM local : Ollama dans Docker (GPU NVIDIA utilisé s'il est disponible)
docker run -d --gpus all --name rag-ollama -p 11434:11434 -v rag-ollama:/root/.ollama ollama/ollama:latest
docker exec rag-ollama ollama pull ministral-3:3b
```

Sans GPU NVIDIA, retirer `--gpus all` (génération plus lente). Si PowerShell refuse d'activer l'environnement : `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

## Corpus et indexation

Les documents de Nexalis sont rédigés en Markdown dans `data/sources/` (chaque fichier commence par ses métadonnées : version, date d'effet, statut, sources réelles citées), puis rendus dans leur format cible pour tester le parsing :

```powershell
python -m scripts.build_corpus     # data/sources -> data/raw (DOCX, PDF, PDF scanné, MD) + convention Syntec
python -m ingestion.ingest         # data/raw -> chroma_db/ (incrémental : seuls les fichiers modifiés)
python -m ingestion.ingest --reset # reconstruction complète
```

| Document | Format | Ce qu'il teste |
| --- | --- | --- |
| Convention collective Syntec (90 articles) | Markdown | jeu de test public annoté (100 questions) |
| Accord télétravail 2025 / 2023 (obsolète) | DOCX | privilégier la version en vigueur |
| Accord temps de travail, forfait jours, RTT | PDF | tableaux, calcul des RTT |
| Guide des congés et absences | PDF | accord plus favorable que la loi |
| Notice mutuelle et prévoyance | PDF | tableaux de garanties sur plusieurs pages |
| Charte informatique | DOCX | règles IT |
| Guide de dépannage IT | Markdown | procédures pas à pas |
| Notes de frais et déplacements | PDF | barème kilométrique, plafonds |
| Livret d'accueil | **PDF scanné** | OCR (RapidOCR via Docling) |
| 11 fiches convention Syntec (salaires minima 2025, événements familiaux et parentalité 2026, congés payés, durée du travail et forfait jours, heures supplémentaires et dimanche, période d'essai et préavis, indemnités de licenciement et retraite, maladie, déplacements, travail hybride, égalité professionnelle) | PDF, Word, Markdown, **PDF scanné** | règles de branche à jour, rédigées à partir des textes de Légifrance et des fiches du Code du travail numérique |

Pipeline d'ingestion : Docling (PDF, DOCX → Markdown, OCR des scans) → titres re-hiérarchisés pour les PDF → découpage par titres puis 256 tokens BGE-M3 (tableaux jamais coupés, fragments < 100 tokens fusionnés, chaque chunk préfixé par « Document > Section ») → embeddings BGE-M3 → ChromaDB avec métadonnées (document, version, statut, section, page).

## Lancer l'API

```powershell
uvicorn app.main:app --port 7860
```

- Interface web : http://localhost:7860/ui (voir plus bas ; à construire une fois)
- Swagger : http://localhost:7860/docs
- Santé : http://localhost:7860/health

Le démarrage prend de 20 à 70 s (chargement de BGE-M3). La première réponse d'Ollama est plus lente (chargement du modèle).

```powershell
Invoke-RestMethod -Method Post -Uri http://localhost:7860/ask `
  -ContentType "application/json; charset=utf-8" `
  -Body '{"question": "Combien de jours de télétravail par semaine ?"}'
```

| Méthode | Route | Rôle |
| --- | --- | --- |
| `POST` | `/ask` | `{"question": "..."}` → `{"answer", "sources", "request_id"}` ; en-tête `Server-Timing` avec la durée de chaque étape |
| `POST` | `/ask/stream` | même chose en Server-Sent Events : `sources`, puis `token` (au fil de l'eau), puis `done` |
| `POST` | `/feedback` | `{"request_id", "rating": 1 ou -1}` : pouce haut / bas, relié à la requête dans MLflow |
| `POST` | `/ingest` | réindexation (rôle admin) |
| `POST` | `/api/admin/documents` | ajout d'un document (rôle admin, multipart) : PDF, PDF scanné (OCR), Word, Markdown ; indexé aussitôt |
| `DELETE` | `/api/admin/documents/{doc}` | retrait d'un document ajouté depuis l'interface (le corpus de référence est protégé) |
| `GET` | `/health` | état, modèle, nombre de chunks indexés, commit déployé |
| `GET` | `/ui` | interface web (application React servie par l'API) |
| `GET` | `/api/config`, `/api/whoami`, `/api/documents`, `/api/documents/{doc}/chunks`, `/api/reports`, `/api/monitoring` | données de l'interface, en lecture seule, même clé d'API que `/ask` |

## Interface web

Une application React servie par l'API elle-même sur `/ui` (même conteneur, en plus du Swagger), pensée pour la démonstration :

| Page | Contenu |
| --- | --- |
| Vue d'ensemble | chiffres clés, trajet d'une question (CPU / GPU), configuration en service lue sur l'API, avancement des 9 itérations |
| Le projet | la documentation pour l'évaluateur : le besoin, comment lire le site, les 9 itérations dans l'ordre (objectif, réalisation, résultat, lien vers la preuve), l'architecture, les choix chiffrés, les limites, comment reproduire |
| Assistant | chat en streaming, citations cliquables reliées aux extraits (document, section, page, score), durée recherche / génération, pouces haut et bas, cas « hors périmètre » et « bloqué RGPD » visibles |
| Corpus | les 21 documents, leurs métadonnées et sources réelles, le découpage en chunks de chacun (tableaux rendus) ; avec une clé admin, ajout de documents (PDF, scan, Word, Markdown) indexés aussitôt, et retrait de ces ajouts |
| Évaluation | recherche (taille des chunks, hybride contre rerankers, coût des rerankers, seuil de refus), réponses (prompt v2 / v3, 8B sur ZeroGPU, par type, chaque question avec réponse attendue et obtenue), modèle (quantization en local et sur ZeroGPU), sécurité (20 messages Faker) |
| Tests | rapport pytest par fichier, noms des tests lisibles, commandes pour relancer les mesures |
| Monitoring | questions suivies dans MLflow en direct : volumes, refus, latence par étape, feedback |

```powershell
cd frontend
npm install
npm run build                       # -> app/static/ui, servi par l'API sur /ui
cd ..
python -m scripts.export_reports    # met à jour les pages Évaluation et Tests (relance pytest)
```

Développement de l'interface avec rechargement à chaud : API sur le port 7861 (`uvicorn app.main:app --port 7861`), puis `npm run dev` dans `frontend/` (http://localhost:5173/ui).

Choix de conception :
- **React + Vite + Tailwind**, et non Gradio comme prévu au plan : l'interface est servie par FastAPI (même image Docker), ZeroGPU n'impose Gradio que pour le Space du LLM. Swagger reste disponible.
- **Système visuel** : `frontend/DESIGN.md` (analyse du design system de Vercel, [awesome-design-md](https://github.com/voltagent/awesome-design-md)), règles anti « AI slop » de [Taste Skill](https://www.tasteskill.dev/) (un fond, une encre, un accent ; pas de dégradés, de flou ni d'émojis ; deux polices, Geist et Geist Mono), thèmes clair et sombre.
- **Accessibilité et détails** : [Web Interface Guidelines](https://github.com/vercel-labs/agent-skills/tree/main/skills/web-design-guidelines) de Vercel (focus visibles, libellés, `aria-live`, mouvement réduit, état dans l'URL, `Intl` pour nombres et dates, typographie française).
- **Graphiques** : palette validée pour le daltonisme dans les deux thèmes, un seul axe par graphique, chaque graphique a son tableau de valeurs.
- **Vérification** : captures à 1440, 768 et 390 px et contrôle du défilement horizontal avec [playwright-cli](https://github.com/microsoft/playwright-cli).

### Le modèle de langage

| `LLM_PROVIDER` | Usage |
| --- | --- |
| `ollama` (défaut) | développement : Ministral 3 3B quantifié, local, aucune minute GPU ZeroGPU consommée |
| `zerogpu` | production : Space Gradio `space/app.py` (Ministral 3 8B), `HF_TOKEN` + `LLM_SPACE_ID` dans `.env` |
| `mistral` | API Mistral (provisoire, ancienne configuration) |
| `static` | réponse fixe, pour les tests |

Tous respectent l'interface `app/llm/base.py` (`generate` et `stream`).

### Le Space ZeroGPU

`space/` contient le Space Gradio (privé) qui sert le LLM : Ministral 3 8B Instruct chargé avec transformers, décoré par `@spaces.GPU` (le GPU n'est attribué que pendant la génération). Deux points d'API : `/generate` (streaming, utilisé par `/ask/stream`) et `/generate_json` (réponse complète + mesures : temps de génération, tokens/s, VRAM au pic, GPU).

```powershell
python -m scripts.deploy_space            # publie space/ sur LLM_SPACE_ID et attend qu'il soit en service
python -m scripts.deploy_space --status   # état du Space
```

Variables du Space : `MODEL_ID`, `QUANTIZATION` (`bf16`, `int8` ou `nf4` via bitsandbytes), `MAX_NEW_TOKENS`, `TEMPERATURE`, `GPU_DURATION`. Le tokenizer de Ministral 3 doit être chargé avec `fix_mistral_regex=True`, sinon le découpage en tokens est faux.

Un Space ZeroGPU se met en pause après une période d'inactivité : le relancer (`--status` l'indique) avant une démonstration.

## Sécurité et RGPD

- **Questions avec données personnelles bloquées** (HTTP 400, message explicatif) : numéro de sécurité sociale (clé vérifiée), IBAN (modulo 97), carte bancaire (Luhn), e-mail, téléphone. Les 20 messages Faker de `eval/pii_messages.jsonl` sont tous bloqués, aucune des 68 questions légitimes ne l'est.
- **Jamais de contenu dans les journaux** ; un filtre masque en plus toute donnée personnelle (`[EMAIL]`, `[IBAN]`...).
- **Clés d'API** : `API_KEYS="cle1:employe,cle2:admin"`, en-tête `X-API-Key` (bouton *Authorize* dans Swagger). Vide = authentification désactivée (local uniquement).
- **Limite de débit** : 30 requêtes par minute et par clé (`RATE_LIMIT_PER_MINUTE`).
- **Injection de prompt** : extraits et question entre balises, traités comme des données.

Détails : [docs/note_rgpd.md](docs/note_rgpd.md).

## Évaluation et MLflow

```powershell
python -m eval.eval_retrieval --dataset syntec --grid full     # grille de chunking (100 questions Syntec)
python -m eval.eval_retrieval --dataset nexalis --hybrid       # recherche hybride sur les questions Nexalis
python -m eval.analyze_gating                                  # seuil de refus sans LLM
python -m eval.eval_answers                                    # réponses de bout en bout (LLM_PROVIDER)
$env:LLM_PROVIDER="zerogpu"; python -m eval.eval_answers       # idem avec le 8B sur ZeroGPU
python -m eval.compare_quantization                            # GGUF en local (Ollama), 20 questions
python -m eval.compare_quantization --backend zerogpu          # 8B en bf16 / int8 / nf4 sur ZeroGPU
python -m scripts.bench_reranker BAAI/bge-reranker-v2-m3       # latence d'un reranker sur CPU
python -m eval.judge eval/results/answers_zerogpu_….jsonl --backend hf --bill-to ynov   # LLM juge
python -m scripts.finops                                       # budget pour 1 000 utilisateurs par jour
python -m eval.register_config                                 # enregistre la configuration retenue dans le registre

mlflow ui --backend-store-uri sqlite:///mlflow.db              # http://localhost:5000
```

Expériences MLflow : `retrieval-chunking` (un run par configuration), `answers-nexalis` (un run par évaluation de bout en bout), `quantization` (un run par variante de modèle), `requests` (un run par question posée à l'API : latences par étape, nombre de chunks, scores, tokens, modèles, version de l'index, feedback ; jamais le texte de la question). Registre de modèles : `assistant-rag-nexalis` (configuration complète du RAG en « models from code », alias `production`).

Jeu d'évaluation maison `eval/questions.jsonl` : 81 questions, dont 71 avec réponse attendue (13 sur les fiches Syntec), document et section (10 pièges : version obsolète, contradiction convention/accord, information dans un tableau, calculs) et 10 hors périmètre.

## Tests

```powershell
pytest          # sans réseau ni modèle chargé
ruff check .
```

Intégration continue (`.github/workflows/ci.yml`, à chaque push et pull request) : ruff + pytest, build de l'interface, et build de l'étape Docker de l'interface.

## Docker

```powershell
python -m ingestion.ingest           # l'index chroma_db/ est copié dans l'image
docker compose up --build            # API (port 7860) + Ollama + MLflow (port 5000)
docker compose exec ollama ollama pull ministral-3:3b   # premier lancement uniquement
```

Sans compose, avec l'Ollama déjà lancé sur la machine :

```powershell
docker build -t rag-api:local .
docker run -d --name rag-api -p 7860:7860 --env-file .env -e OLLAMA_BASE_URL=http://host.docker.internal:11434 rag-api:local
```

Interface : http://localhost:7860/ui (la racine `/` y redirige). Image d'environ 8,8 Go, dont BGE-M3 (2,3 Go), torch CPU et Docling ; démarrage en ~12 s. Avec compose, chaque question est suivie dans le serveur MLflow `rag-mlflow` (http://localhost:5000), qui alimente la page Monitoring ; sans compose (et sur Azure), dans une base SQLite du conteneur (`MLFLOW_TRACKING_URI`).

Le Dockerfile construit l'interface web (étape Node), installe torch en version CPU, télécharge BGE-M3 ainsi que les modèles de Docling et de l'OCR au build (aucun téléchargement à l'exécution), copie l'index, les documents sources et le rapport d'évaluation, et tourne en utilisateur non root. Docling est embarqué pour l'ajout de documents depuis l'interface.

## Déploiement (Azure)

L'API tourne sur **Azure Container Apps** (région Allemagne de l'Ouest), le LLM sur le **Space ZeroGPU**. Mise en ligne continue : chaque fusion sur `main` lance la CI, puis, si elle réussit, `.github/workflows/deploy.yml` construit l'image, la pousse dans Azure Container Registry, déploie une nouvelle révision et vérifie que `/health` renvoie bien le nouveau commit. Infrastructure créée une fois par `scripts/azure_provision.ps1`. Détails, coûts et arrêt : [docs/deploiement_azure.md](docs/deploiement_azure.md).

Latences mesurées en production (14/10/2026, 8 questions sur l'URL publique, en-tête `Server-Timing` de `/ask`, médianes hors première question) :

| Étape | Médiane |
| --- | --- |
| Embedding de la question (BGE-M3, CPU Azure) | 189 ms |
| Recherche vectorielle (ChromaDB) | 8 ms |
| Recherche lexicale (BM25) | 4 ms |
| Génération (Space ZeroGPU, aller-retour) | 2,0 s |
| **Total côté API** | **2,2 s** |
| Total vu du navigateur (réseau compris) | 2,8 s |
| Question hors périmètre (refus sans appel au LLM) | 0,2 s |
| Première question après une période d'inactivité (GPU réattribué) | 10 s |

Le goulot est la génération (environ 90 % du temps) : la recherche complète tient en moins de 0,2 s sur CPU. L'API démarre en une quinzaine de secondes (chargement de BGE-M3).

## Arborescence

```
RAG_Ynov/
├── app/                    API FastAPI
│   ├── main.py             Routes /ask, /ask/stream, /feedback, /ingest, /health, /ui
│   ├── dashboard.py        Routes /api/* de l'interface (config, corpus, rapports, monitoring)
│   ├── admin.py, documents.py  Ajout et retrait de documents depuis l'interface (rôle admin)
│   ├── reports/            Rapport d'évaluation consolidé (scripts/export_reports.py)
│   ├── config.py           Configuration (variables d'environnement, .env)
│   ├── prompts.py          Prompt système, phrase de refus, garde-fous
│   ├── llm/                Fournisseurs de LLM : Ollama, ZeroGPU, Mistral, static
│   ├── rag/                Embeddings, Chroma, BM25, retriever hybride, reranker
│   ├── security/           Filtre RGPD, clés d'API, limite de débit, filtre de logs
│   ├── monitoring/         Suivi MLflow des requêtes et du feedback
│   └── services/           Assistant : recherche puis génération
├── frontend/               Interface web React (Vite, Tailwind) + DESIGN.md ; build -> app/static/ui
├── ingestion/              Parsing Docling, découpage, indexation idempotente
├── data/sources/           Documents Nexalis en Markdown (source de vérité, avec métadonnées)
├── data/raw/               Documents rendus (PDF, DOCX, scan, MD) + metadata.json
├── eval/                   Jeux de questions, scripts d'évaluation, résultats CSV
├── scripts/                Corpus, export des rapports, rerankers, déploiement du Space, FinOps
├── space/                  Space Gradio ZeroGPU (LLM de production)
├── docs/                   Plan d'action, résultats, note RGPD, budget
├── .github/workflows/      Intégration continue et déploiement continu sur Azure
├── tests/                  Tests pytest
├── Dockerfile, docker-compose.yml
└── requirements*.txt       API / ingestion / développement
```
