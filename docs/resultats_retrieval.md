# Résultats : chunking, recherche hybride, reranking

Mesures du 13/10/2026, machine de développement (i5-1240P, 16 threads, CPU uniquement pour la recherche). Scripts : `eval/eval_retrieval.py`, `eval/analyze_gating.py`, `scripts/bench_reranker.py`. Chaque configuration est un run MLflow (expérience `retrieval-chunking`, base `mlflow.db`). CSV bruts dans `eval/results/`.

## Jeux de questions

| Jeu | Questions | Vérité terrain | Remarque |
| --- | --- | --- | --- |
| Syntec (MTEB-French, lyon-nlp) | 100 | l'article de la convention qui contient la réponse | questions synthétiques, proches du texte de l'article |
| Nexalis (`eval/questions.jsonl`) | 58 avec réponse (+ 10 hors périmètre) | document + section attendus | questions « d'employé », vocabulaire courant, pièges (version obsolète, contradiction, tableau, calcul) |

Un résultat compte comme trouvé si un chunk du top-k couvre l'article (Syntec) ou la section du document attendu (Nexalis). `ctx@5` = tokens envoyés au LLM avec les 5 premiers chunks.

## 1. Taille de chunk (Syntec, recherche vectorielle seule)

Découpage par titres puis par tokens BGE-M3, fusion des fragments < 100 tokens, embeddings BGE-M3.

| Taille | Overlap | Chunks | R@1 | R@3 | R@5 | R@8 | MRR@10 | ctx@5 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 256 | 0 % | 118 | 0,70 | 0,91 | 0,95 | 0,96 | 0,803 | 1 135 |
| **256** | **10 %** | 120 | 0,70 | 0,90 | **0,95** | 0,96 | 0,802 | **1 129** |
| 256 | 20 % | 124 | 0,71 | 0,91 | 0,94 | 0,96 | 0,806 | 1 143 |
| 384 | 10 % | 97 | 0,71 | 0,93 | 0,95 | 0,96 | 0,808 | 1 394 |
| 512 | 0 % | 86 | 0,72 | 0,94 | 0,96 | 0,96 | 0,818 | 1 536 |
| 512 | 10 % | 87 | 0,71 | 0,93 | 0,96 | 0,96 | 0,812 | 1 548 |
| 768 | 0 % | 77 | 0,72 | 0,94 | 0,96 | 0,96 | 0,822 | 1 782 |
| 1024 | 0 % | 75 | 0,73 | 0,94 | 0,96 | 0,96 | 0,827 | 1 806 |
| par article | — | 70 | 0,71 | 0,93 | 0,96 | 0,97 | 0,816 | 2 003 |

Le recall@5 varie de 2 points seulement entre toutes les configurations : la taille compte peu sur ce jeu, l'overlap pas du tout. **Règle du plan** (plus petite taille à moins de 2 points du meilleur recall@5) : **256 tokens, 10 % d'overlap**, qui envoie 26 % de tokens en moins au LLM que 512 (1 129 contre 1 548).

Le jeu Nexalis confirme : en recherche vectorielle seule, 256 tokens donne le meilleur MRR (0,890 contre 0,870 en 512 et 0,859 en 768), avec le même recall@5 (0,95).

## 2. Les échecs restants : des mots exacts

Sur Nexalis, les 3 questions ratées par la recherche vectorielle à toutes les tailles :

| Question | Ce qui est remonté à la place |
| --- | --- |
| « Combien est payée une semaine d'**astreinte** ? » | articles Syntec sur la rémunération |
| « Ai-je droit à un jour de congé pour **déménager** ? » | Syntec « changement de résidence » |
| « Je suis déjà couvert par la mutuelle obligatoire de mon **conjoint**… » | autres sections de la notice mutuelle |

Le mot décisif est présent tel quel dans le bon chunk : c'est le cas typique où une recherche lexicale aide.

## 3. Recherche hybride et rerankers (Nexalis, 256 tokens)

Recherche hybride = BM25 (racinisation Snowball française, sans accents ni mots vides) fusionné avec la recherche vectorielle par Reciprocal Rank Fusion (k = 60), `app/rag/lexical.py`.

| Configuration | R@1 | R@3 | R@5 | R@8 | MRR@10 | Latence recherche |
| --- | --- | --- | --- | --- | --- | --- |
| Vecteurs seuls | 0,84 | 0,95 | 0,95 | 0,95 | 0,890 | ~2 ms |
| Vecteurs + reranker mMiniLMv2 (multilingue, 118 M) | 0,84 | 0,95 | 0,97 | 0,98 | 0,897 | 1,0 s |
| Vecteurs + reranker bge-reranker-v2-m3 (568 M) | 0,84 | 0,98 | 0,98 | 0,98 | 0,914 | **12,6 s** |
| **Hybride BM25 + vecteurs** | **0,90** | **0,98** | **0,98** | **1,00** | **0,939** | **~6 ms** |
| Hybride + reranker mMiniLMv2 | 0,84 | 0,97 | 0,97 | 1,00 | 0,904 | 1,1 s |

Latences de recherche hors embedding de la question (en cache pendant l'évaluation) ; l'embedding BGE-M3 de la question coûte ~100 à 200 ms sur CPU.

- La recherche hybride fait mieux que le meilleur reranker, pour 2 000 fois moins de temps.
- **bge-reranker-v2-m3 est inutilisable en production CPU** : 15 s par question pour 20 passages sur la machine de développement (`scripts/bench_reranker.py`), davantage sur un conteneur Azure à 2 vCPU.
- Ajouter un reranker léger après la recherche hybride dégrade le classement.

Sur Syntec, la recherche hybride coûte 2 points de recall@5 (0,93 contre 0,95) et ~0,02 de MRR : les questions y sont des paraphrases du texte, BM25 apporte surtout du bruit. Baisser le poids de BM25 dans la fusion (0,3 / 0,5 / 0,7) ne rattrape pas ces 2 points et dégrade Nexalis. On privilégie Nexalis, plus proche de l'usage réel.

## 4. Refuser sans appeler le LLM

`eval/analyze_gating.py` : meilleur score cosinus obtenu par chaque question.

| Seuil sur le meilleur cosinus | Hors périmètre écartés (sur 10) | Questions légitimes écartées (sur 58) |
| --- | --- | --- |
| 0,465 | 8 | 1 |
| 0,445 | 5 | 0 |
| **0,425** | **4** | **0** |
| 0,405 | 3 | 0 |

Seuil retenu : **0,42** (`RETRIEVAL_MIN_SCORE`) avec une marge de 0,045 sous la question légitime la moins bien notée. Les hors-périmètre restants sont refusés par le LLM (phrase de refus imposée par le prompt). Avec ~40 % des questions hors sujet écartées avant le LLM, autant de minutes ZeroGPU sont économisées.

## Configuration retenue

| Paramètre | Valeur |
| --- | --- |
| Découpage | titres, puis 256 tokens BGE-M3, overlap 25 tokens (10 %), fusion < 100 tokens |
| Embeddings | BAAI/bge-m3 (CPU) |
| Recherche | hybride BM25 + vecteurs (RRF, poids 1/1), 20 candidats, top 5 |
| Reranker | désactivé (option : mMiniLMv2) |
| Filtre | documents obsolètes exclus |
| Seuil de refus | cosinus du meilleur chunk < 0,42 |
| Contexte envoyé au LLM | ~1 150 tokens (objectif du plan : ≤ 2 500) |

Objectifs du plan : recall@5 ≥ 90 % ✔ (0,98 Nexalis, 0,93 Syntec), MRR ≥ 0,75 ✔ (0,94 / 0,78), contexte ≤ 2 500 tokens ✔.
