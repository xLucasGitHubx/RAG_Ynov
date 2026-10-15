# Note RGPD — Assistant documentaire Nexalis

Version du 13/10/2026. Périmètre : API FastAPI de l'assistant RH/IT (développement local ; le déploiement Azure + Hugging Face sera précisé à l'itération 5).

## Finalité

Répondre aux questions RH et IT des salariés de Nexalis Conseil à partir des documents internes (accords, guides, chartes). L'assistant n'a pas besoin de données personnelles pour remplir cette finalité : il ne doit ni en recevoir, ni en conserver.

## Données traitées

| Donnée | Traitée ? | Conservée ? | Où |
| --- | --- | --- | --- |
| Texte de la question | Oui, le temps de la requête | **Non** (jamais journalisée) | Mémoire de l'API ; extraits + question envoyés au LLM |
| Longueur de la question, durées, scores, nombre de tokens | Oui | Oui (suivi qualité) | MLflow (`mlflow.db`) |
| Réponse générée | Oui, renvoyée au salarié | Non (seule sa longueur) | — |
| Pouce haut / bas | Oui | Oui | MLflow, relié à l'identifiant aléatoire de la requête |
| Commentaire libre du feedback | Reçu | **Non** (seule sa longueur) | — |
| Clé d'API | Oui (authentification) | Non : seule une empreinte SHA-256 tronquée (8 caractères) apparaît dans les journaux | — |
| Documents internes | Oui | Oui | Index Chroma (`chroma_db/`), dans l'API |

Aucune adresse IP, aucun nom ni identifiant de salarié n'est enregistré par l'application.

## Mesures techniques

1. **Filtre d'entrée** (`app/security/pii.py`) : les questions contenant un numéro de sécurité sociale (avec contrôle de la clé), un IBAN (contrôle modulo 97), un numéro de carte bancaire (algorithme de Luhn), une adresse e-mail ou un numéro de téléphone français sont **bloquées** (HTTP 400) avec un message explicatif. Elles ne sont ni envoyées au modèle, ni journalisées : seul le type de donnée détecté est tracé.
   - Test : les 20 messages générés avec Faker (`eval/pii_messages.jsonl`) sont tous bloqués ; aucune des 81 questions légitimes du jeu d'évaluation n'est bloquée (`tests/test_security.py`).
   - Limite : les noms propres et adresses postales ne sont pas détectés par les expressions régulières. Piste : Microsoft Presidio avec un modèle spaCy français.
2. **Journaux** : le contenu des questions n'est jamais écrit. Un filtre de journalisation (`app/security/logging_filter.py`) masque en plus toute donnée personnelle qui apparaîtrait dans un message (exception de bibliothèque, etc.).
3. **Authentification** : clé d'API par en-tête `X-API-Key`, deux rôles (`employe`, `admin` pour la réindexation et l'ajout de documents). Limitation à 30 requêtes par minute et par clé.
4. **Injection de prompt** : extraits et question délimités par des balises ; le prompt système impose de traiter leur contenu comme des données, jamais comme des instructions, et de ne répondre qu'à partir des extraits.
5. **Minimisation côté LLM** : seuls la question et les 5 extraits les plus pertinents sont envoyés au modèle. En local, le modèle tourne sur la machine (Ollama) : rien ne sort du poste.
6. **Ajout de documents** (rôle admin, page Corpus) : réservé aux documents internes à diffuser à tous les salariés (accords, chartes, procédures). Un document contenant des données personnelles (fiche de paie, dossier individuel) n'a pas sa place dans le corpus : l'assistant pourrait le citer à n'importe quel salarié. Le contrôle repose sur l'administrateur ; seuls les documents ajoutés de cette façon peuvent être retirés depuis l'interface (fichier, métadonnées et chunks supprimés ensemble).

## Durées de conservation

| Donnée | Durée proposée |
| --- | --- |
| Journaux applicatifs (sans contenu) | 6 mois (aligné sur la charte informatique, article 9) |
| Métriques MLflow par requête et feedbacks | 12 mois, puis agrégation |
| Index des documents | Tant que le document est en vigueur ; retiré à la réindexation suivante |
| En production (Azure) : métriques MLflow et documents ajoutés depuis l'interface | Jusqu'au déploiement suivant : ils vivent sur le disque du conteneur, effacé à chaque nouvelle version |

## Droits des personnes

Les requêtes ne sont rattachées à aucune personne : il n'existe pas de données nominatives à effacer ou à communiquer. Une demande d'effacement porte donc sur les feedbacks éventuels, identifiables uniquement si le salarié fournit l'identifiant de requête (`request_id`) renvoyé par l'API ; la suppression se fait alors dans MLflow (suppression du run).

## Hébergement

- **API, index, documents, base MLflow** : Azure Container Apps, région **Allemagne de l'Ouest** (Union européenne). L'abonnement étudiant n'autorise pas la région France Centre.
- **LLM** : Space Hugging Face privé (ZeroGPU). La question et les 5 extraits retenus y transitent pour la génération ; le Space ne conserve rien et n'appelle aucune API tierce. Hugging Face est une entreprise américaine : pour une mise en production réelle, un GPU dédié hébergé dans l'UE (même région Azure) supprimerait ce transfert. Point à valider avec l'intervenant (voir le plan d'action, section Risques).
- Les questions bloquées par le filtre d'entrée ne quittent jamais l'API.
