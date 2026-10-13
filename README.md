# Assistant documentaire RH/IT (RAG) — Nexalis Conseil

Projet fil rouge Ynov, module « Industrialisation de l'IA dans le Cloud ».

Un assistant virtuel qui répond aux questions RH et IT des employés (congés, télétravail, mutuelle, pannes) en s'appuyant uniquement sur les documents internes de l'entreprise fictive Nexalis Conseil, avec un LLM open-weight auto-hébergé.

## État d'avancement

| Itération | Sujet | État |
| --- | --- | --- |
| 1 | Squelette : API FastAPI, `/ask`, Swagger | Fait |
| 2 | Conteneurisation : Dockerfile multi-stage | Fait (mis à jour pour le RAG) |
| 3 | Mémoire : corpus, ingestion Docling, chunking mesuré, BGE-M3, ChromaDB | Fait |
| 4 | Cerveau : Ollama local, recherche hybride, streaming SSE | Fait en local, **sans interface** ; Space ZeroGPU écrit, non déployé |
| 5 | Déploiement : Azure Container Apps + Space ZeroGPU | À faire |
| 6 | Optimisation : quantization | À faire (benchmark rerankers fait) |
| 7 | Sécurité et RGPD | Fait (local) |
| 8 | MLOps avec MLflow | Fait (local) : runs d'évaluation, suivi par requête, feedback |
| 9 | FinOps et documentation | À faire |

Résultats détaillés : [docs/resultats_retrieval.md](docs/resultats_retrieval.md) (chunking, recherche hybride, rerankers) et [docs/resultats_reponses.md](docs/resultats_reponses.md) (réponses de bout en bout). Note RGPD : [docs/note_rgpd.md](docs/note_rgpd.md).

## Architecture (développement local)

```
Question ──> API FastAPI (CPU)
              ├─ filtre RGPD (NIR, IBAN, carte, e-mail, téléphone) ─> 400 si données perso
              ├─ clé d'API + rôle, limite de débit
              ├─ recherche hybride : BGE-M3 (Chroma) + BM25, fusion RRF, versions obsolètes exclues
              ├─ meilleur score < 0,42 ─> « je ne sais pas » sans appeler le LLM
              ├─ prompt : 5 extraits délimités + règles anti-injection
              └─ LLM : Ollama (Ministral 3 3B, GGUF Q4) en local ── plus tard : Space ZeroGPU
            ─> réponse + sources (document, section, page) + request_id ─> suivi MLflow
```

Tout ce qui n'a pas besoin de GPU (parsing, embeddings, recherche, sécurité, suivi) tourne sur CPU. Seule la génération utilise le GPU.

## Prérequis

- Python 3.12 ([python.org](https://www.python.org/downloads/))
- Docker Desktop ([docker.com](https://www.docker.com/products/docker-desktop/)) : sert à faire tourner Ollama
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

Pipeline d'ingestion : Docling (PDF, DOCX → Markdown, OCR des scans) → titres re-hiérarchisés pour les PDF → découpage par titres puis 256 tokens BGE-M3 (tableaux jamais coupés, fragments < 100 tokens fusionnés, chaque chunk préfixé par « Document > Section ») → embeddings BGE-M3 → ChromaDB avec métadonnées (document, version, statut, section, page).

## Lancer l'API

```powershell
uvicorn app.main:app --port 7860
```

- Swagger : http://localhost:7860/docs
- Santé : http://localhost:7860/health

Le démarrage prend ~20 s (chargement de BGE-M3). La première réponse d'Ollama est plus lente (chargement du modèle).

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
| `GET` | `/health` | état, modèle, nombre de chunks indexés |

### Le modèle de langage

| `LLM_PROVIDER` | Usage |
| --- | --- |
| `ollama` (défaut) | développement : Ministral 3 3B quantifié, local, aucune minute GPU ZeroGPU consommée |
| `zerogpu` | production (itération 4 bis) : Space Gradio `space/app.py`, `HF_TOKEN` + `LLM_SPACE_ID` |
| `mistral` | API Mistral (provisoire, ancienne configuration) |
| `static` | réponse fixe, pour les tests |

Tous respectent l'interface `app/llm/base.py` (`generate` et `stream`).

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
python -m eval.eval_answers                                    # réponses de bout en bout (Ollama)
python -m scripts.bench_reranker BAAI/bge-reranker-v2-m3       # latence d'un reranker sur CPU

mlflow ui --backend-store-uri sqlite:///mlflow.db              # http://localhost:5000
```

Expériences MLflow : `retrieval-chunking` (un run par configuration), `answers-nexalis` (un run par évaluation de bout en bout), `requests` (un run par question posée à l'API : latences par étape, nombre de chunks, scores, tokens, modèles, version de l'index, feedback ; jamais le texte de la question).

Jeu d'évaluation maison `eval/questions.jsonl` : 68 questions, dont 58 avec réponse attendue, document et section (10 pièges : version obsolète, contradiction convention/accord, information dans un tableau, calculs) et 10 hors périmètre.

## Tests

```powershell
pytest          # 86 tests, sans réseau ni modèle chargé
ruff check .
```

## Docker

```powershell
python -m ingestion.ingest           # l'index chroma_db/ est copié dans l'image
docker compose up --build            # API (port 7860) + Ollama
docker compose exec ollama ollama pull ministral-3:3b   # premier lancement uniquement
```

Le Dockerfile installe torch en version CPU, télécharge BGE-M3 au build (aucun téléchargement au démarrage), copie l'index et tourne en utilisateur non root. Docling n'est pas embarqué : réindexer = reconstruire l'image (corpus fixe).

## Arborescence

```
RAG_Ynov/
├── app/                    API FastAPI
│   ├── main.py             Routes /ask, /ask/stream, /feedback, /ingest, /health
│   ├── config.py           Configuration (variables d'environnement, .env)
│   ├── prompts.py          Prompt système, phrase de refus, garde-fous
│   ├── llm/                Fournisseurs de LLM : Ollama, ZeroGPU, Mistral, static
│   ├── rag/                Embeddings, Chroma, BM25, retriever hybride, reranker
│   ├── security/           Filtre RGPD, clés d'API, limite de débit, filtre de logs
│   ├── monitoring/         Suivi MLflow des requêtes et du feedback
│   └── services/           Assistant : recherche puis génération
├── ingestion/              Parsing Docling, découpage, indexation idempotente
├── data/sources/           Documents Nexalis en Markdown (source de vérité, avec métadonnées)
├── data/raw/               Documents rendus (PDF, DOCX, scan, MD) + metadata.json
├── eval/                   Jeux de questions, scripts d'évaluation, résultats CSV
├── scripts/                Génération du corpus, benchmark des rerankers
├── space/                  Space Gradio ZeroGPU (production, non déployé)
├── docs/                   Plan d'action, résultats, note RGPD
├── tests/                  Tests pytest
├── Dockerfile, docker-compose.yml
└── requirements*.txt       API / ingestion / développement
```
