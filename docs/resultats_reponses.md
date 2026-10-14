# Résultats : réponses de bout en bout (LLM local, puis ZeroGPU)

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

## Prompt v3 (version retenue)

Ajout d'une consigne : une question pratique fermée (« puis-je… ? », « est-ce limité à… ? ») se répond par oui ou non à partir de la règle générale présente dans les extraits.

| Métrique | v2 | **v3** |
| --- | --- | --- |
| Réponses correctes | 89,7 % (52 / 58) | **91,4 % (53 / 58)** |
| Faux refus | 5,2 % | **0 %** |
| Hors périmètre refusés | 10 / 10 | 10 / 10 |
| Bon document cité | 94,8 % | **100 %** |
| Pièges « version obsolète » | 66,7 % | **100 %** |

Deux questions (it-07, nf-03) n'avaient pas pu être générées le 13/10 (Ollama en échec, portable en surchauffe) ; relancées le 14/10, machine reposée, elles sont toutes deux correctes. v3 est donc évalué sur les 58 questions.

Échecs restants :

| Question | Réponse v3 | Commentaire |
| --- | --- | --- |
| it-02 données client dans ChatGPT | « Non, … IA génératives publiques interdites » | **verdict juste**, mais ne mentionne pas l'assistant IA interne autorisé (attendu par le critère) |
| it-05 clé USB personnelle | « Non. Les supports amovibles personnels sont interdits. » | **verdict juste**, sans l'alternative (clés chiffrées fournies) attendue par le critère |
| mu-01 part employeur | « 54 %, 102 % et 138 % » | erreur : montants du tableau lus comme des pourcentages |
| mu-02 coût pour un salarié seul | « 90 € » | erreur : cotisation totale au lieu de la part salarié (36 €) |
| la-01 période d'essai d'un cadre | « 3 mois » | erreur de lecture (le texte dit 4 mois) |

Les critères n'ont pas été assouplis après coup pour it-02 et it-05 : une réponse complète doit donner l'alternative autorisée. En ne comptant que le verdict, v3 serait à 55 / 58 (94,8 %).

Les 3 erreurs de lecture de chiffres (tableau mutuelle, période d'essai) relèvent de la taille du modèle (3B quantifié 4 bits) : à remesurer avec Ministral 3 8B bf16 sur ZeroGPU.

## Modèle de production : Ministral 3 8B bf16 sur ZeroGPU (14/10/2026)

Même chaîne, même prompt v3, mêmes critères ; seul le LLM change : `LLM_PROVIDER=zerogpu python -m eval.eval_answers` appelle le Space `Lulu18/rag-llm` (tranche MIG 48 Go d'une RTX PRO 6000 Blackwell). Fichier : `eval/results/answers_zerogpu_v3_20261014_1407.jsonl`.

| Métrique | 3B Q4 local (v3) | **8B bf16 ZeroGPU** |
| --- | --- | --- |
| Réponses correctes (68 questions) | 63 / 68 (92,6 %) | **66 / 68 (97,1 %)** |
| Questions avec réponse | 53 / 58 | **56 / 58** |
| Hors périmètre refusés | 10 / 10 | 10 / 10 |
| Bon document cité | 100 % | 100 % |
| Temps de génération (médiane, mesuré dans le Space) | 14 s (portable) | **1,5 s** |
| Aller-retour complet (médiane) | — | 2,5 s |
| Vitesse de génération | ~19 tokens/s | ~27 tokens/s |
| VRAM au pic | — | 17,1 Go |

Le 8B corrige les trois erreurs de lecture du 3B (mu-01, mu-02, la-01) et donne l'alternative attendue pour it-02. Échecs restants :

| Question | Réponse 8B | Commentaire |
| --- | --- | --- |
| it-05 clé USB personnelle | « Non… les supports amovibles personnels sont interdits » | **verdict juste**, sans l'alternative (clés chiffrées) : même échec que le 3B |
| sy-01 préavis de démission d'un cadre | « 1 mois… 2 mois après 2 ans » | **erreur** : le modèle applique la ligne ETAM du tableau Syntec au lieu de celle des cadres (3 mois) |

sy-01 est une vraie erreur, et instructive : le bon article était bien dans les extraits, mais le tableau mélange plusieurs catégories de salariés. Piste : découper les tableaux de la convention par catégorie, ou ajouter au prompt une consigne de vérifier la ligne du tableau qui correspond à la catégorie demandée.

Le temps GPU mesuré (1,5 s) remplace l'hypothèse de 8 s du plan dans `docs/estimation_budget.md`.

## Quantization (itération 6)

Script : `python -m eval.compare_quantization` (MLflow : expérience `quantization`). Échantillon fixe de 20 questions couvrant tous les types (factuelles, tableaux, calculs, pièges, 2 hors périmètre), mêmes critères que ci-dessus.

### Sur ZeroGPU : Ministral 3 8B en bf16, int8 et nf4 (bitsandbytes)

Le script change la variable `QUANTIZATION` du Space, attend son redémarrage, mesure, puis remet bf16.

| Variante | Correctes | Génération (médiane) | Aller-retour (médiane) | Tokens/s | VRAM au pic |
| --- | --- | --- | --- | --- | --- |
| **bf16** (retenu) | 20 / 20 | 1,6 s | 2,5 s | 31 | 17,2 Go |
| int8 (LLM.int8) | 20 / 20 | 8,0 s | 9,3 s | 7 | 10,0 Go |
| nf4 (4 bits) | 20 / 20 | 2,4 s | 3,5 s | 22 | 6,7 Go |

- **Aucune perte de qualité mesurable** sur l'échantillon, quelle que soit la quantization.
- **int8 est un mauvais choix** : 5 fois plus lent que bf16 (le calcul en précision mixte de LLM.int8 coûte cher) pour seulement 40 % de VRAM en moins.
- **nf4 est le bon compromis pour un GPU dédié** : 2,6 fois moins de VRAM pour 50 % de temps en plus. Le modèle tiendrait sur une T4 16 Go (0,40 $/h) au lieu d'une L4 24 Go (0,80 $/h).
- **bf16 reste retenu sur ZeroGPU** : la VRAM y est gratuite (tranche de 48 Go) et seul le temps GPU est décompté.

### En local : modèles GGUF via Ollama (GTX 1650, 4 Go de VRAM)

| Modèle | Correctes | Temps LLM (médiane) | Tokens/s | Mémoire (part en VRAM) |
| --- | --- | --- | --- | --- |
| 3B q4_K_M | 15 / 20 | 14 s | 19 | — |
| **3B q8_0** | **19 / 20** | 23 s | 10 | 4,8 Go (27 %) |
| 8B q4_K_M | 18 / 20 | 84 s | 3 | 6,4 Go (23 %) |

Sur un portable, la quantization 4 bits du 3B coûte cher en qualité (erreurs de lecture de tableaux) ; le 3B en q8_0 est le meilleur modèle de développement, le 8B ne tient pas dans la carte graphique et tourne surtout sur CPU.
