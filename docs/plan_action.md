# Plan d'action — Assistant documentaire RAG auto-hébergé

Oct 13, 2026 · @Lucas

## Résumé et décisions clés

On construit un assistant RH/IT en français qui répond uniquement à partir des documents internes (PDF, Word, TXT), avec un LLM open-weight auto-hébergé sur ZeroGPU Hugging Face (40 min de GPU par jour via l'organisation de l'école).

La contrainte qui structure tout : **ZeroGPU ne fonctionne qu'avec le SDK Gradio**, pas avec Docker ni FastAPI directement. On sépare donc le projet en deux services.

| Décision | Choix retenu | Pourquoi |
| --- | --- | --- |
| Découpage | API FastAPI (Docker sur Azure, CPU) + Space Gradio d'inférence (ZeroGPU) | Respecte le sujet (API + Dockerfile) et la contrainte Gradio de ZeroGPU |
| LLM | Modèle 7–8B instruct multilingue, en bf16 sur ZeroGPU, en GGUF 4 bits en local | Tient largement dans les 48 Go de VRAM, bon en français |
| Embeddings | Modèle multilingue sur CPU, dans l'API | Pas de GPU consommé à l'ingestion ni à la recherche |
| Base vectorielle | ChromaDB persistant | Simple, filtrage par métadonnées, demandé par le sujet |
| Parsing | Docling (PDF, DOCX, PPTX, HTML vers Markdown) | Un seul outil pour tous les formats, garde titres et tableaux |
| Chunking | Découpage par structure (titres) puis par taille, taille choisie par mesure | Voir section dédiée : on ne fixe pas la taille au hasard |
| Développement | LLM local quantifié (Ollama / llama.cpp) | Les 40 minutes sont réservées aux tests réels et à la démo |
| Corpus | Entreprise fictive bâtie sur des sources publiques et citées | Crédibilité et traçabilité de chaque réponse |

Le principe à garder en tête : tout ce qui n'a pas besoin de GPU (parsing, embeddings, recherche, auth, filtre RGPD, logs) tourne sur CPU. Le GPU ne sert qu'à la génération de la réponse.

## Architecture cible

&#91;embedded content: architecture cible · API sur Azure + Space GPU Hugging Face + ingestion + MLflow\]

L'API FastAPI (Docker, CPU) fait tout le travail de recherche et de sécurité, puis envoie un seul prompt au Space Gradio ZeroGPU, qui renvoie la réponse. En développement, ce Space est remplacé par Ollama en local derrière la même interface `LLMBackend` : zéro minute GPU consommée.

## Stack technique recommandée

Le couple de base est **Ministral 3 8B Instruct** pour la génération et **BGE-M3** pour les embeddings : tous deux open-weight, licences permissives, solides en français.

| Brique | Choix principal | Alternative | Où ça tourne | Justification |
| --- | --- | --- | --- | --- |
| LLM (prod) | [Ministral 3 8B Instruct 2512](https://huggingface.co/mistralai/Ministral-3-8B-Instruct-2512-BF16), bf16 | Qwen3-8B, Llama 3.1 8B Instruct | Space Gradio ZeroGPU | Apache 2.0, français supporté nativement, bon respect du prompt système, contexte 256k. \~17 Go en bf16 pour 48 Go de VRAM disponibles |
| LLM (dev) | Ministral 3 3B ou 8B en GGUF Q4\_K\_M | Qwen3-4B | PC local (Ollama / llama.cpp) | Zéro minute GPU consommée pendant le développement |
| Embeddings | [BAAI/bge-m3](https://huggingface.co/BAAI/bge-m3) (1024 dim, 8192 tokens) | Solon-embeddings-large (FR), multilingual-e5-large | API, CPU | Meilleur score retrieval MTEB-French parmi les modèles open (\~0,65 NDCG@10), licence MIT |
| Reranker | BAAI/bge-reranker-v2-m3 | Aucun (option) | API, CPU | Reclasse les 20 meilleurs chunks en 5 : gain de précision sans GPU |
| Parsing | [Docling](https://github.com/docling-project/docling) | pymupdf4llm (PDF), python-docx | API, CPU | PDF, DOCX, PPTX, HTML vers Markdown structuré (titres, tableaux) |
| Découpage | LangChain `MarkdownHeaderTextSplitter` + `RecursiveCharacterTextSplitter` (en tokens) | LlamaIndex `SentenceSplitter` | API | Coupe d'abord par titres, puis par taille |
| Base vectorielle | ChromaDB (mode persistant) | FAISS, Qdrant | API | Métadonnées filtrables (source, page, section) |
| API | FastAPI + Uvicorn, SSE pour le streaming | Flask | Azure Container Apps (CPU) | Swagger natif, demandé par le sujet |
| Appel LLM | `gradio_client` avec token HF | requêtes HTTP directes | API vers Space GPU | Client officiel pour appeler un Space Gradio |
| Sécurité | Clé API ou JWT + Microsoft Presidio (FR) et regex | Regex seules | API | Bloque n° de sécu, IBAN, email, téléphone |
| MLOps | MLflow (tracking + évaluation) | — | API ou local | Demandé par le sujet |
| Évaluation | RAGAS + script maison (recall@k, MRR) | LLM-as-judge | Local | Mesure retrieval et qualité des réponses |

À vérifier le jour du choix final : les sorties de modèles vont vite, un nouveau 8B peut être apparu. Le critère reste le même : open-weight, bon en français, moins de 20 Go en bf16.

## Corpus et jeux de test sourcés

L'entreprise fictive est une ESN, **Nexalis Conseil** (environ 350 salariés, Toulouse et Paris), qui relève de la convention collective Syntec. Ce choix n'est pas un hasard : il existe un jeu de test français public, annoté à la main, construit exactement sur ce texte.

### Le jeu de test de référence : Syntec (MTEB-French)

Le dataset [lyon-nlp/mteb-fr-retrieval-syntec-s2p](https://huggingface.co/datasets/lyon-nlp/mteb-fr-retrieval-syntec-s2p) contient les 90 articles de la convention Syntec et 100 questions créées manuellement, chacune reliée à l'article qui contient la réponse. Il a été construit par Wikit AI et publié avec le benchmark [MTEB-French](https://arxiv.org/abs/2405.20468) (Ciancone et al., 2024).

C'est notre vérité terrain pour mesurer le retrieval et choisir la taille des chunks : on sait pour chaque question quel article doit remonter. La licence du dataset n'est pas renseignée sur Hugging Face ; le texte de la convention lui-même est public sur Légifrance (IDCC 1486). On le cite et on l'utilise uniquement à des fins d'évaluation.

### Les documents de Nexalis Conseil

Chaque document interne fictif est bâti sur une source publique réelle, citée dans son pied de page. Les formats sont volontairement mélangés pour tester le parsing.

| Document interne | Format | Source réelle qui sert de base | Ce qu'il teste |
| --- | --- | --- | --- |
| Convention collective applicable | TXT / Markdown | Articles Syntec du dataset ci-dessus | Questions de référence annotées |
| Accord télétravail (version 2025) | DOCX | Un vrai accord d'ESN publié dans la [base ACCO](https://www.data.gouv.fr/datasets/acco-accords-dentreprise) (Légifrance), anonymisé et adapté | Règles chiffrées, conditions d'éligibilité |
| Accord télétravail (version 2023, obsolète) | DOCX | Même base, version antérieure | Le RAG doit privilégier la version en vigueur |
| Accord temps de travail, forfait jours et RTT | PDF texte | Base ACCO + modalités Syntec | Calculs, exceptions par statut (ETAM / cadres) |
| Guide des congés et absences | PDF texte | Fiches [Service Public](https://entreprendre.service-public.gouv.fr/P10004) (congés payés, maladie, événements familiaux), Licence Ouverte | Accord plus favorable que la convention (ex. 27 jours au lieu de 25) |
| Notice mutuelle et prévoyance | PDF avec tableaux | Fiche Service Public « complémentaire santé d'entreprise » + garanties fictives rédigées par l'équipe, en français | Extraction de tableaux de garanties |
| Charte informatique | DOCX | Guides ANSSI : [hygiène informatique en 42 mesures](https://messervices.cyber.gouv.fr/guides/en-guideline-healthy-information-system-42-measures) et charte d'utilisation des moyens informatiques (PME/ETI) | Règles IT, sanctions, usages interdits |
| Guide de dépannage IT (VPN, MFA, mot de passe, imprimante) | Markdown | Rédigé par l'équipe, cohérent avec la charte | Procédures pas à pas |
| Notes de frais et déplacements | PDF texte | Articles 50 à 60 Syntec + barème kilométrique public | Montants, plafonds |
| Livret d'accueil | PDF **scanné** (image) | Rédigé par l'équipe | OCR de Docling |

La base ACCO publie depuis 2017 les accords d'entreprise réels (télétravail, temps de travail, congés). Les fiches Service Public sont réutilisables librement en citant la source et la date de mise à jour. C'est ce qui rend le corpus crédible : chaque règle de Nexalis existe vraiment quelque part.

### Le jeu d'évaluation maison (à construire)

- **50 questions sur Nexalis**, chacune avec réponse attendue, document source et page.
- Dont **10 hors périmètre** (« Quel est le cours de l'action Nexalis ? ») : la bonne réponse est « je ne sais pas ».
- Dont **5 pièges** : version obsolète, contradiction convention/accord, info présente uniquement dans un tableau.
- **20 messages avec données personnelles** générés avec Faker (`fr_FR` : n° de sécu, IBAN, téléphone) pour tester le filtre RGPD.
- Méthode : un LLM propose des questions à partir de chaque chunk, puis on relit et corrige à la main. Le jeu est versionné dans le Git (`eval/questions.jsonl`).

## Stratégie de chunking optimisée

Point de départ : **découpage par titres, puis 512 tokens avec 64 tokens d'overlap (12 %)**. La taille finale est choisie par une mesure sur le jeu Syntec, pas par intuition.

Les études publiques convergent sur un point : il n'existe pas de taille universelle. Chroma a mesuré jusqu'à 9 points de recall d'écart entre stratégies sur un même corpus ([Chroma Research, 2024](https://research.trychroma.com/evaluating-chunking)). NVIDIA trouve que le découpage par page ou par section est le plus stable sur des PDF structurés ([NVIDIA, 2025](https://developer.nvidia.com/blog/finding-the-best-chunking-strategy-for-accurate-ai-responses/)). Pour des questions factuelles courtes, comme des questions RH, la fourchette 256 à 512 tokens revient le plus souvent ([synthèse premai, 2026](https://blog.premai.io/rag-chunking-strategies-the-2026-benchmark-guide)).

### Les règles de découpage

1. **Parser en Markdown avec Docling** pour garder titres, listes et tableaux.
2. **Couper par titres** (`#`, `##`, `###`) : un article de convention ou d'accord reste un bloc logique.
3. **Redécouper les sections trop longues** avec un splitter récursif (paragraphe, phrase, mot), en comptant les **tokens du tokenizer de BGE-M3**, pas les caractères.
4. **Ne jamais couper un tableau** : un tableau de garanties mutuelle = un chunk, avec son titre.
5. **Fusionner les fragments de moins de 100 tokens** avec le chunk voisin (titres orphelins, pieds de page).
6. **Préfixer chaque chunk par son chemin** : « Accord télétravail 2025 > Article 3 > Éligibilité ». Le chunk se comprend seul et le retrieval s'améliore.
7. **Stocker les métadonnées** : document, version, date d'effet, page, section, type (RH / IT). Elles servent au filtrage (exclure les versions obsolètes) et à la citation des sources.

### Le protocole de mesure (itération 3, réutilisé en itération 8)

Un script `eval_retrieval.py` reconstruit l'index pour chaque combinaison et la note sur les 100 questions Syntec, puis sur les 50 questions Nexalis. Chaque run est enregistré dans MLflow.

| Paramètre | Valeurs testées |
| --- | --- |
| Taille de chunk (tokens) | 256, 384, 512, 768, 1024, et « par article » sans redécoupage |
| Overlap | 0 %, 10 %, 20 % |
| Top-k récupéré | 3, 5, 8 |
| Reranker | sans, avec (top-20 reclassé en top-5) |

| Métrique | Ce qu'elle dit | Seuil visé |
| --- | --- | --- |
| Recall@5 | La bonne source est-elle dans les 5 premiers chunks ? | ≥ 90 % |
| MRR@10 | À quel rang arrive la bonne source ? | ≥ 0,75 |
| Tokens de contexte envoyés | Coût et latence côté GPU | ≤ 2 500 |
| Taux de « je ne sais pas » correct | Questions hors périmètre bien refusées | ≥ 90 % |

**Règle de décision** : on retient la plus petite taille dont le recall@5 est à moins de 2 points du meilleur. Un chunk plus petit envoie moins de tokens au LLM, donc consomme moins de minutes ZeroGPU. L'hypothèse de départ, à confirmer par la mesure : 384 ou 512 tokens, 10 % d'overlap, top-5 après reranking.

Les seuils sont des objectifs de projet, à ajuster après le premier run de référence.

## Plan d'action par itération

Les itérations 1 à 4 se font entièrement en local, sans consommer de GPU. ZeroGPU entre en jeu à partir de l'itération 4 bis (bascule du backend LLM) et sert surtout aux itérations 5, 6 et 8.

### Itération 1 : le squelette

- [ ] Initialiser le repo Git : `app/`, `ingestion/`, `eval/`, `data/raw/`, `docs/`, `pyproject.toml` ou `requirements.txt`
- [ ] FastAPI : `POST /ask` (entrée `{"question": str}`, sortie `{"answer": str, "sources": []}`) et `GET /health`
- [ ] Modèles Pydantic pour la requête et la réponse, réponse statique « Bonjour, je suis l'assistant RH »
- [ ] Vérifier le Swagger sur `/docs`

**Fini quand** : `curl` sur `/ask` répond et le Swagger est accessible.

### Itération 2 : la conteneurisation

- [ ] Dockerfile multi-stage sur `python:3.12-slim`, utilisateur non root, `EXPOSE 7860` (port repris dans la config Azure)
- [ ] `.dockerignore` (données brutes, `.venv`, index)
- [ ] `docker-compose.yml` pour le local (API + MLflow plus tard)
- [ ] Mesurer la taille de l'image et la noter dans le README

**Fini quand** : `docker run -p 7860:7860 rag-api` suffit, sans Python installé.

### Itération 3 : la mémoire

- [ ] Constituer le corpus Nexalis (section Corpus) dans `data/raw/`, avec un fichier `SOURCES.md` qui cite chaque source
- [ ] Pipeline `ingestion/ingest.py` : Docling, découpage par titres puis par tokens, embeddings BGE-M3, écriture ChromaDB
- [ ] Ingestion idempotente : un hash par fichier, on ne réindexe que ce qui a changé
- [ ] Brancher la recherche sémantique sur `/ask` (renvoie les chunks et leurs sources)
- [ ] Script `eval/eval_retrieval.py` sur les 100 questions Syntec : premier run de référence, puis la grille de tailles

**Fini quand** : recall@5 mesuré et taille de chunk choisie, chiffres à l'appui.

### Itération 4 : le cerveau

- [ ] Interface `LLMBackend` avec deux implémentations : `OllamaBackend` (local) et `ZeroGPUBackend` (Space HF)
- [ ] Prompt système en français : répondre uniquement à partir du contexte, citer les sources, dire « je ne sais pas » sinon, température 0,1 à 0,2
- [ ] Ajouter le reranker et le filtrage par métadonnées (versions en vigueur uniquement)
- [ ] Streaming SSE : `POST /ask/stream`
- [ ] Créer le Space Gradio privé `rag-llm` (ZeroGPU) : modèle chargé au niveau module, fonction `generate()` décorée `@spaces.GPU(duration=30)`
- [ ] Tester le jeu Nexalis (50 questions) en local, puis 10 questions sur ZeroGPU

* [ ] Interface utilisateur (attendue en plus du Swagger) : chat Gradio monté dans FastAPI avec `gr.mount_gradio_app` sur `/ui`, qui appelle `/ask/stream`, affiche les sources cliquables et un pouce haut / bas

**Fini quand** : réponses sourcées correctes, refus propre sur les questions hors périmètre.

### Itération 5 : le déploiement cloud

- [ ] Activer Azure for Students (e-mail Ynov), créer le groupe de ressources `rg-rag` et une alerte de budget
- [ ] Déployer l'API sur Azure Container Apps : image construite dans Azure Container Registry, accès externe sur le port 7860, secrets (`HF_TOKEN`, `LLM_SPACE_ID`, `API_KEYS`)
- [ ] Persistance : index Chroma et modèles intégrés à l'image Docker (corpus fixe), réindexation = nouveau build
- [ ] CI/CD GitHub Actions : tests, puis build et déploiement sur Container Apps à chaque merge sur `main`
- [ ] Mesurer les latences par étape : recherche, reranking, démarrage à froid Azure, file d'attente ZeroGPU, génération. Identifier le goulot

**Fini quand** : URL publique (protégée) qui répond, tableau des latences dans le README.

### Itération 6 : l'optimisation

- [ ] Comparer sur ZeroGPU : bf16, INT8 et NF4 4 bits (bitsandbytes), mesurer VRAM, tokens/s et qualité sur le jeu Nexalis
- [ ] Comparer en local : GGUF Q8\_0, Q5\_K\_M, Q4\_K\_M
- [ ] Optimiser le pipeline : contexte réduit (taille de chunk choisie, top-k), embeddings en ONNX ou quantifiés, cache des questions fréquentes
- [ ] Ajuster `duration` de `@spaces.GPU` au temps réel mesuré

**Fini quand** : tableau comparatif VRAM / latence / qualité et choix argumenté.

### Itération 7 : la sécurité et le RGPD

- [ ] Authentification : clé API en en-tête ou JWT, deux rôles (employé, admin RH pour `/ingest`)
- [ ] Filtre d'entrée : regex (n° de sécu, IBAN, carte bancaire, email, téléphone) + Presidio en français ; requête bloquée avec un message explicatif
- [ ] Masquer les données personnelles dans les logs avant écriture
- [ ] Garde-fou contre l'injection de prompt : contexte délimité, instructions système non surchargeables
- [ ] Rate limiting par clé, HTTPS (fourni par HF), note RGPD (finalité, durée de conservation des logs, droit à l'effacement)

**Fini quand** : les 20 messages Faker sont tous bloqués, aucun en clair dans les logs.

### Itération 8 : MLOps avec MLflow

- [ ] Tracker chaque requête : latence par étape, nombre de chunks, scores de similarité, tokens, backend, version du modèle et de l'index
- [ ] Tracker chaque run d'évaluation : paramètres RAG (taille, overlap, top-k, reranker) et métriques (recall@5, MRR, fidélité RAGAS)
- [ ] Endpoint `POST /feedback` (pouce haut / bas) relié au run MLflow
- [ ] Enregistrer la configuration retenue dans le registre de modèles

**Fini quand** : dashboard MLflow avec l'historique des requêtes et la comparaison des runs de chunking.

### Itération 9 : FinOps et documentation

- [ ] Estimation pour 1 000 utilisateurs par jour, deux scénarios : ZeroGPU + crédits, et GPU dédié (voir section Budget)
- [ ] README complet : architecture, installation, choix techniques chiffrés, limites
- [ ] Fichier `docs/estimation_budget.md` avec les hypothèses explicites

**Fini quand** : le repo se clone et se lance en une commande, budget justifié ligne par ligne.

## Déployer l'API sur Azure (Azure for Students)

L'API Docker tourne sur **Azure Container Apps** : tu fournis une image, Azure la lance en HTTPS sans serveur à gérer. [Azure for Students](https://azure.microsoft.com/free/students/) donne 100 $ de crédit valables 12 mois, sans carte bancaire en principe, et un registre d'images Azure Container Registry (1 registre Standard, 100 Go) gratuit pendant 12 mois. Le Space GPU reste chez Hugging Face : l'API l'appelle par Internet avec `HF_TOKEN`.

### Pas à pas

1. **Activer Azure for Students** avec ton e-mail Ynov (réservé aux étudiants, vérification du statut).
2. **Installer Azure CLI**, puis `az login`.
3. **Adapter le Dockerfile** (ci-dessous) : modèles et index sont embarqués dans l'image. Retire `data/raw/` du `.dockerignore`, l'index est construit au build.
4. **Lancer les commandes** du bloc suivant depuis la racine du repo.
5. **Tester** : `az containerapp up` affiche l'URL publique en `*.azurecontainerapps.io`. Swagger sur `/docs`, interface sur `/ui`.
6. **Créer une alerte de budget** dans Cost Management (par exemple 20 $) pour surveiller le crédit.

```dockerfile
FROM python:3.12-slim
RUN useradd -m -u 1000 appuser
USER appuser
ENV HOME=/home/appuser PATH=/home/appuser/.local/bin:$PATH HF_HOME=/home/appuser/hf
WORKDIR /home/appuser/app
COPY --chown=appuser requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Modèles embarqués dans l'image : aucun téléchargement au démarrage
RUN python -c "from huggingface_hub import snapshot_download as d; d('BAAI/bge-m3'); d('BAAI/bge-reranker-v2-m3')"
COPY --chown=appuser . .
# Index Chroma construit au build à partir de data/raw
RUN python -m ingestion.ingest
EXPOSE 7860
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860"]
```

```bash
az login
az extension add --name containerapp --upgrade
az provider register --namespace Microsoft.App
az provider register --namespace Microsoft.OperationalInsights
az group create --name rg-rag --location francecentral

# Depuis la racine du repo : construit l'image dans Azure, crée le registre
# et l'environnement, puis lance l'application
az containerapp up --name rag-api --resource-group rg-rag --location francecentral \
  --source . --ingress external --target-port 7860

# Secrets et ressources
az containerapp secret set --name rag-api --resource-group rg-rag \
  --secrets hf-token=<TON_TOKEN_HF> api-keys=<CLE1,CLE2>
az containerapp update --name rag-api --resource-group rg-rag \
  --cpu 2 --memory 4Gi --min-replicas 0 --max-replicas 1 \
  --set-env-vars HF_TOKEN=secretref:hf-token API_KEYS=secretref:api-keys LLM_SPACE_ID=<ton-user>/rag-llm
```

Les options de la CLI évoluent : en cas d'erreur, `az containerapp up --help` fait foi.

### Le Space GPU (Hugging Face)

Crée un Space **Gradio** avec le matériel ZeroGPU : sur ton compte perso (un compte vérifié de plus de 30 jours peut en héberger 2 gratuitement), ou dans l'organisation ynov si l'école te donne le droit d'y créer. L'API l'appelle ainsi :

```python
from gradio_client import Client
client = Client(os.environ["LLM_SPACE_ID"], token=os.environ["HF_TOKEN"])  # ou hf_token= selon la version
answer = client.predict(prompt, api_name="/generate")
```

À vérifier dès le premier appel : que les 40 minutes de l'école sont bien décomptées pour ton compte quand le Space est hébergé hors de l'organisation.

### CI/CD (itération 5)

Avec le code sur GitHub, ce workflow teste puis redéploie à chaque push sur `main`. Le secret `AZURE_CREDENTIALS` se crée avec `az ad sp create-for-rbac --name rag-ci --role contributor --scopes /subscriptions/<id>/resourceGroups/rg-rag --sdk-auth`. Si l'abonnement refuse la création d'un principal de service, garde les tests en CI et déploie à la main avec `az containerapp up`, en le notant dans le README.

```yaml
name: Deploy to Azure Container Apps
on:
  push:
    branches: [main]
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run tests
        run: pip install -r requirements.txt && pytest
      - uses: azure/login@v2
        with:
          creds: ${{ secrets.AZURE_CREDENTIALS }}
      - name: Deploy
        run: |
          az extension add --name containerapp --upgrade
          az containerapp up --name rag-api --resource-group rg-rag --source .
```

### Pièges à connaître

- **Éligibilité** : Azure for Students vérifie le statut étudiant. En cas de refus, demande à l'intervenant un accès via l'Azure Education Hub.
- **Persistance** : le disque d'un conteneur est éphémère. Le corpus étant fixe, l'index et les modèles sont dans l'image ; changer un document = nouveau build.
- **RAM** : BGE-M3 et le reranker demandent environ 3 à 4 Go. Si le conteneur est tué faute de mémoire, passer à `--memory 8Gi` (4 vCPU) ou à un modèle d'embeddings plus léger.
- **Démarrage à froid** : avec `--min-replicas 0`, l'application s'arrête sans trafic et la première requête attend le chargement des modèles. La veille de la démo : `--min-replicas 1`, puis remettre 0 après.
- **Région** : France Central ; si l'abonnement étudiant refuse, prendre une région proposée par le portail.
- **Coût** : le plan Consommation facture le temps de calcul réellement utilisé. Un seul registre à créer pour rester dans l'offre gratuite. À la fin du module : `az group delete --name rg-rag`.
- **Latence** : un aller-retour Azure vers Hugging Face s'ajoute à chaque question ; elle est mesurée en itération 5.

## Budget ZeroGPU : bien utiliser les 40 minutes

40 minutes par jour, c'est environ **300 réponses générées** si une génération prend 8 secondes de GPU. C'est largement assez pour tester et faire la démo, à condition de ne jamais développer sur le GPU.

Ce qu'il faut savoir sur le quota ([doc officielle ZeroGPU](https://huggingface.co/docs/hub/spaces-zerogpu)) :

- Le GPU par défaut est une **demi RTX Pro 6000 Blackwell, 48 Go de VRAM**. La taille `xlarge` (96 Go) consomme le quota deux fois plus vite : inutile pour un 8B.
- Le quota est consommé **par compte appelant**. Les 40 minutes sont par étudiant : à 4 dans le groupe, 160 minutes par jour en tout. Un appel non authentifié n'a droit qu'à 2 minutes : l'API doit appeler le Space avec le `HF_TOKEN` d'un membre de l'organisation de l'école.
- Le quota se recharge **24 h après la première utilisation**, pas à minuit. Lancer les tests importants tôt dans la journée.
- La durée par défaut d'une fonction GPU est de 60 s. Déclarer une durée plus courte (`duration=30`) améliore la priorité dans la file.
- `torch.compile` n'est pas supporté ; la compilation ahead-of-time l'est (PyTorch 2.8+).
- Au-delà du quota, un compte PRO ou Team peut payer en crédits : **1 $ pour 10 minutes**.

| Activité | Où | Minutes GPU |
| --- | --- | --- |
| Développement de l'API, du pipeline, des prompts | Local (Ollama) | 0 |
| Grille de chunking (retrieval seul) | Local, CPU | 0 |
| Test de fumée après chaque déploiement (10 questions) | ZeroGPU | \~2 |
| Évaluation complète du jeu Nexalis (50 questions) | ZeroGPU | \~7 |
| Comparaison de quantization (3 formats × 20 questions) | ZeroGPU | \~8 |
| Démo de soutenance | ZeroGPU | garder 40 min libres ce jour-là |

Le temps de 8 s par génération est une estimation (environ 300 tokens générés à partir de 2 500 tokens de contexte). On le mesure dès l'itération 4 et on met à jour ce tableau.

### Pour l'estimation FinOps (itération 9)

Hypothèse : 1 000 utilisateurs, 3 questions par jour chacun, 8 s de GPU par réponse.

- 3 000 réponses × 8 s = **400 minutes GPU par jour**.
- Avec ZeroGPU : 40 min incluses + 360 min en crédits = **36 $ par jour**, soit environ 790 $ par mois sur 22 jours ouvrés.
- À comparer avec un GPU dédié loué au mois (Spaces GPU ou Inference Endpoints), à chiffrer avec la grille tarifaire en vigueur. ZeroGPU n'offre pas de garantie de disponibilité : pour une vraie production, le GPU dédié est le bon argument.
- Ajouter l'API CPU, le stockage de l'index et MLflow, faibles mais à lister.

## Risques et points à valider avec l'intervenant

Le risque principal est architectural : le sujet demande une API Docker, ZeroGPU impose Gradio. Le découpage en deux services le résout, mais il faut le faire valider tôt.

| Risque | Impact | Parade |
| --- | --- | --- |
| ZeroGPU limité au SDK Gradio | Impossible de mettre FastAPI et le GPU dans un seul conteneur | Deux services : API Docker sur Azure (CPU) + Space Gradio sur Hugging Face (GPU), appel via `gradio_client` |
| Quota épuisé avant une démo ou un test | Plus de génération pendant 24 h | Backend Ollama local en secours, même interface `LLMBackend` |
| File d'attente ZeroGPU aux heures chargées | Latence imprévisible | La mesurer et la présenter comme goulot en itération 5 ; `duration` courte pour la priorité |
| Disque éphémère des conteneurs Azure | Index Chroma perdu à chaque redémarrage | Index et modèles intégrés à l'image Docker, réindexation = nouveau build |
| Données qui transitent par Hugging Face | Discutable vis-à-vis de « aucune fuite » | Seuls la question et les extraits envoyés au modèle passent chez Hugging Face, documents et index restent sur Azure ; Space privé, aucune API tierce ; le dire explicitement dans le README |
| Licence floue du dataset Syntec | Réutilisation contestable | Usage limité à l'évaluation, source citée, texte public sur Légifrance |
| PDF scannés mal lus | Chunks vides ou faux | OCR de Docling, contrôle du nombre de caractères extraits par page |

### Réponses de l'intervenant et point encore ouvert

- [x] Architecture : option A retenue (API Docker CPU + Space Gradio ZeroGPU)
- [x] Quota : 40 minutes **par étudiant**, chacun teste avec son propre compte
- [x] Interface utilisateur : **attendue** en plus du Swagger
- [x] Notation de la qualité : **métriques chiffrées et démo**, les deux comptent
- [x] Hébergement : hypothèse de travail retenue, Azure + Hugging Face sont acceptés. Pour mémoire : si Hugging Face peut récupérer les données, l'auto-hébergement ne compte pas. Question à reformuler à l'intervenant : « un hébergeur cloud qui exécute notre modèle sans réutiliser les données est-il accepté, puisque l'itération 5 impose un déploiement cloud ? » En cas de refus, repli sur l'option C (tout dans un conteneur, LLM quantifié sur CPU) directement sur Azure, ce qui supprime tout passage par Hugging Face

## Sources

- [Hugging Face — Spaces ZeroGPU (documentation officielle)](https://huggingface.co/docs/hub/spaces-zerogpu)
- [lyon-nlp/mteb-fr-retrieval-syntec-s2p (Hugging Face)](https://huggingface.co/datasets/lyon-nlp/mteb-fr-retrieval-syntec-s2p)
- [Ciancone et al., MTEB-French (arXiv 2405.20468)](https://arxiv.org/abs/2405.20468)
- [ACCO : Accords d'entreprise (data.gouv.fr)](https://www.data.gouv.fr/datasets/acco-accords-dentreprise)
- [Service Public — mise à disposition des données, Licence Ouverte](https://entreprendre.service-public.gouv.fr/P10004)
- [ANSSI — guide d'hygiène informatique en 42 mesures](https://messervices.cyber.gouv.fr/guides/en-guideline-healthy-information-system-42-measures)
- [Mistral — Ministral 3 8B Instruct 2512 (Hugging Face)](https://huggingface.co/mistralai/Ministral-3-8B-Instruct-2512-BF16)
- [Guide des embeddings pour le français, 2026 (scores MTEB-French)](https://bestllmfor.com/guide/embeddings-francais-modeles/)
- [Chroma Research — Evaluating Chunking Strategies for Retrieval](https://research.trychroma.com/evaluating-chunking)
- [NVIDIA — Finding the Best Chunking Strategy for Accurate AI Responses](https://developer.nvidia.com/blog/finding-the-best-chunking-strategy-for-accurate-ai-responses/)
- [premai — RAG Chunking Strategies: The 2026 Benchmark Guide](https://blog.premai.io/rag-chunking-strategies-the-2026-benchmark-guide)

* [Microsoft — Azure for Students (crédit 100 $, services gratuits, Container Registry)](https://azure.microsoft.com/free/students/)
