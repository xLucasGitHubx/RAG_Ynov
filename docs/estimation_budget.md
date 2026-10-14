# Estimation budgétaire — 1 000 utilisateurs par jour

Version du 14/10/2026. Calcul reproductible : `python -m scripts.finops` (toutes les hypothèses sont des paramètres ; le temps GPU par réponse est lu dans la dernière évaluation ZeroGPU, `eval/results/answers_zerogpu_*.jsonl`).

## Hypothèses

| Hypothèse | Valeur | Justification |
| --- | --- | --- |
| Utilisateurs actifs | 1 000 par jour ouvré | énoncé du projet |
| Questions par utilisateur | 3 par jour | usage d'un assistant RH/IT (quelques questions ponctuelles) |
| Jours facturés | 22 jours ouvrés par mois | usage interne en entreprise |
| Plage d'activité | 10 h par jour | 8 h – 18 h ; mise à l'échelle à zéro la nuit et le week-end |
| Part des questions qui appellent le LLM | 95 % | ~3 % de refus anticipés (seuil de pertinence, 3 hors-périmètre sur 68 questions de test) et ~2 % de questions bloquées par le filtre RGPD |
| Temps GPU par réponse | **1,48 s (médiane mesurée)** | 65 réponses générées sur le Space ZeroGPU (Ministral 3 8B bf16, ~1 830 tokens de prompt) ; moyenne 1,85 s ; aller-retour complet 2,5 s en médiane |
| API (recherche, sécurité, suivi) | 2 vCPU, 4 Go, une réplique pendant les heures ouvrées | BGE-M3 + index en mémoire ~3 Go |

Les questions qui n'appellent pas le LLM (refus anticipé, blocage RGPD) coûtent seulement du CPU : le seuil de pertinence et le filtre d'entrée sont aussi des leviers d'économie.

**Attention au matériel de la mesure.** ZeroGPU nous a servi une tranche MIG de 48 Go d'une RTX PRO 6000 Blackwell : bien plus rapide qu'une L4. Sur une L4, il faut compter 3 à 4 fois plus (≈ 5 s par réponse) ; c'est l'hypothèse retenue pour dimensionner le GPU dédié.

## Prix utilisés (relevés le 14/10/2026)

| Poste | Prix | Source |
| --- | --- | --- |
| ZeroGPU au-delà du quota | 1 $ pour 10 minutes de GPU | [documentation ZeroGPU](https://huggingface.co/docs/hub/spaces-zerogpu) |
| Quota ZeroGPU inclus | 40 min/jour (compte PRO ou membre d'une organisation Team) ; 5 min pour un compte gratuit | idem |
| Abonnement PRO | 9 $/mois | [huggingface.co/pricing](https://huggingface.co/pricing) |
| GPU dédié 1× L4 24 Go | 0,80 $/h (Space ou Inference Endpoint) | idem |
| GPU dédié 1× L40S 48 Go | 1,80 $/h | idem |
| Azure Container Apps (consommation) | 0,000024 $/vCPU-s actif, 0,000003 $/Gio-s, 0,40 $/million de requêtes ; gratuits : 180 000 vCPU-s, 360 000 Gio-s, 2 M requêtes par mois | API officielle des prix Azure (région East US ; France Central non publiée dans l'API) |
| Azure Container Registry Basic | ~0,15 €/jour (France Central) | API officielle des prix Azure |

## Résultat

| | Calcul | Coût mensuel |
| --- | --- | --- |
| Volume | 3 000 questions/jour → 2 850 appels LLM → **70 min de GPU/jour** (1,48 s par appel) | |
| **Scénario A — ZeroGPU** | (70 − 40) min × 0,10 $ × 22 jours + PRO 9 $ | **≈ 75 $** |
| **Scénario B — GPU dédié L4**, allumé 10 h/jour | 0,80 $ × 10 h × 22 jours ; occupation ≈ 40 % avec 5 s par réponse sur L4 | **≈ 176 $** |
| Scénario B' — GPU dédié L40S (marge mémoire et débit) | 1,80 $ × 10 h × 22 jours | ≈ 396 $ |
| API Azure Container Apps + registre | vCPU 33,7 $ + mémoire 8,4 $ + requêtes 0 $ + registre 5 $ | **≈ 47 $** |
| Stockage index, MLflow, logs | index de quelques Mo dans l'image ; MLflow sur la même instance | négligeable |

**Total : ≈ 122 $/mois avec ZeroGPU, ≈ 223 $/mois avec un GPU L4 dédié.**

La première version de ce document supposait 8 s de GPU par réponse (hypothèse du plan) et arrivait à 757 $ pour ZeroGPU : la mesure divise le coût du scénario A par 10.

## Lecture

- **Sur le papier, ZeroGPU est le moins cher ; en pratique, il reste un outil de démonstration.** 70 min par jour, c'est à peine au-dessus du quota inclus. Mais le service n'offre aucune garantie de disponibilité (file d'attente partagée, Space mis en pause : c'est arrivé pendant le projet), le quota se compte par compte et non par application, et le temps facturé peut dépasser le temps de génération mesuré (réservation de la durée `GPU_DURATION`, chargement du modèle). Avec un aller-retour complet de 2,5 s, le coût passe à ≈ 182 $ : le même ordre de grandeur qu'une L4.
- **Une L4 dédiée suffit largement en charge.** Même à 5 s par réponse, le GPU est occupé 40 % des heures ouvrées. Les pics (arrivée au bureau, veille de congés) se lissent avec une file d'attente ou un serveur d'inférence avec batching (vLLM, TGI). Coût fixe et prévisible, données traitées sur une machine dédiée : c'est le choix recommandé pour la production.
- **Le modèle 8B tient sur 24 Go en bf16** : 17,2 Go de VRAM au pic, mesurés sur ZeroGPU. **En nf4, 6,7 Go seulement, sans perte de qualité mesurée** (20 / 20 sur l'échantillon, 2,4 s au lieu de 1,6 s ; voir `docs/resultats_reponses.md`) : une T4 16 Go à 0,40 $/h suffirait, soit ≈ 88 $/mois au lieu de 176 $ (la T4 est plus lente : débit à mesurer avant de trancher). int8 est à écarter (5 fois plus lent).
- **L'API CPU pèse peu** (~20 % du total en scénario B) : la recherche hybride sans reranker évite d'ajouter un GPU ou des CPU supplémentaires pour un cross-encoder (12 s par question sur CPU, voir `docs/resultats_retrieval.md`).
- **Qualité au rendez-vous** : le 8B bf16 répond correctement à 66 questions sur 68 (97 %) sur ZeroGPU, contre 91 % pour le 3B quantifié en local (voir `docs/resultats_reponses.md`).

## Sensibilité

| Variation | Scénario A (ZeroGPU) | Scénario B (L4) |
| --- | --- | --- |
| Temps GPU de 2,5 s (aller-retour complet) | ≈ 182 $ | inchangé (176 $) |
| Temps GPU de 5 s (équivalent L4) | ≈ 444 $ | 176 $, occupation 40 % |
| 5 questions par utilisateur, 5 s par réponse | ≈ 792 $ | 176 $, occupation 66 % : une L4 suffit encore |
| Activité 24 h/24 | inchangé (facturation à l'usage) | GPU ≈ 422 $, API ≈ 114 $ |

Commandes : `python -m scripts.finops --gpu-seconds 5`, `--questions 5`, `--hours 24`.
