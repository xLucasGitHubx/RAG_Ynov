# Résultats : réponses de bout en bout (LLM local)

Mesures du 13/10/2026. Script : `python -m eval.eval_answers` (expérience MLflow `answers-nexalis`, détails par question dans `eval/results/answers_*.jsonl`).

Chaîne évaluée : filtre RGPD → recherche hybride (256 tokens, BM25 + BGE-M3, top 5, seuil 0,42) → **Ministral 3 3B** (GGUF Q4_K_M via Ollama, température 0,1, contexte 4 096) sur la machine de développement (GTX 1650 4 Go : modèle à 45 % sur GPU, 55 % sur CPU).

## Critères

- **Question avec réponse** (58) : correcte si tous les éléments attendus (chiffres, termes, sous forme d'expressions régulières dans `eval/questions.jsonl`) figurent dans la réponse, sans refus.
- **Question hors périmètre** (10) : correcte si l'assistant répond qu'il ne trouve pas l'information.
- **Source citée** : le document attendu figure dans les sources renvoyées.

Ce critère par mots-clés est strict sur les chiffres (ce qui compte pour des règles RH) mais ne juge pas la qualité rédactionnelle ni la fidélité de chaque phrase : un juge LLM (RAGAS) est prévu avec le modèle 8B de production.

## Prompt v2

| Métrique | Valeur |
| --- | --- |
| Réponses correctes (58 questions) | **89,7 %** (86,2 % avant correction de 2 critères trop stricts, voir plus bas) |
| Hors périmètre correctement refusés | **10 / 10** (dont 3 sans appel au LLM grâce au seuil) |
| Bon document retrouvé par la recherche | 100 % |
| Bon document cité dans les sources | 94,8 % |
| Faux refus | 5,2 % (3 questions) |
| Tokens envoyés au LLM (médiane) | ~1 750 |
| Tokens générés (médiane) | 42 |
| Latence LLM (médiane / 90e centile) | 14 s / 44 s |

Par type de question : factuelles 89,7 %, tableaux 90,9 %, calculs 100 %, contradiction convention / accord 100 %, information seulement dans un tableau 100 %, **version obsolète 66,7 %**.

### Analyse des échecs

| Question | Réponse | Cause |
| --- | --- | --- |
| tdt-08 durée hebdo modalité 2 | « 38 heures et 30 minutes » | **correcte** : critère trop strict (attendait « 38 h 30 »), corrigé |
| mu-05 déjà couvert par le conjoint | « vous n'êtes pas obligé d'adhérer » | **correcte** : critère trop strict (attendait « dispense »), corrigé |
| tt-10 limité à un jour par semaine ? | refus | faux refus sur une question fermée (la règle « 2 jours » était dans le contexte) |
| it-02 données client dans ChatGPT ? | refus | faux refus : la règle « IA génératives publiques interdites » était dans le contexte |
| it-05 clé USB personnelle ? | refus | faux refus, même cause |
| mu-01 part employeur de la mutuelle | « 54 % à 138 % » | erreur du modèle : confond les montants du tableau avec un pourcentage (la phrase « 60 % » était dans le contexte) |
| mu-02 coût mensuel pour un salarié seul | « 90 € » | erreur d'interprétation : cotisation totale au lieu de la part salarié (36 €) |
| la-01 période d'essai d'un cadre | « 3 mois » | erreur de lecture du modèle (le texte OCR dit bien 4 mois pour les cadres) |

Les 3 faux refus portent sur des questions pratiques fermées (« puis-je… ? », « est-ce limité à… ? ») : le petit modèle ne fait pas le lien entre la question et une règle générale. Le prompt v3 ajoute une consigne explicite sur ce cas.

Les erreurs restantes (lecture de tableau, chiffre voisin) sont typiques d'un modèle 3B quantifié en 4 bits ; elles sont à remesurer avec Ministral 3 8B en bf16 sur ZeroGPU (itération 4 bis), qui est le modèle de production.

### Latence locale

La latence est dominée par le LLM (embedding + recherche < 300 ms). Elle a fortement varié pendant l'évaluation (10 s au début, 40 à 90 s à la fin) : le portable chauffe après plusieurs heures de calcul (GPU à 81 °C, CPU bridé à 2,1 GHz) et le modèle ne tient pas entièrement dans les 4 Go de VRAM. Ce n'est pas représentatif de la production, où la génération se fera sur GPU ZeroGPU.
