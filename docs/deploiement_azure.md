# Déploiement sur Azure Container Apps

Architecture : l'API (image Docker de ce dépôt : FastAPI, interface `/ui`, index, BGE-M3, Docling, base MLflow) tourne sur **Azure Container Apps**. Le LLM reste sur le **Space Hugging Face ZeroGPU** (`LLM_PROVIDER=zerogpu`). L'image est construite par GitHub Actions et stockée dans **Azure Container Registry**.

```
Fusion sur main ── CI ── GitHub Actions ── build ──> Azure Container Registry ── pull (identifiants du registre) ──> Container Apps ──> Space ZeroGPU
```

## 1. Une seule fois, sur votre machine

1. **Installer Azure CLI** : https://learn.microsoft.com/cli/azure/install-azure-cli-windows (puis rouvrir le terminal).
2. **Se connecter** avec le compte de l'abonnement (Azure for Students / crédits Ynov) :

   ```powershell
   az login
   az account show --query name -o tsv     # vérifier l'abonnement
   ```

3. **Créer l'infrastructure** (groupe de ressources, registre, environnement, application) :

   ```powershell
   .\scripts\azure_provision.ps1
   ```

   L'environnement Container Apps créé est de type « Express » (défaut de l'extension az) : il refuse l'identité managée, le registre est donc accédé avec ses identifiants administrateur, fournis à la création de l'application. Un environnement « standard » est resté bloqué en « Waiting » sur l'abonnement étudiant, qui n'autorise de toute façon qu'**un seul** environnement. Secrets et variables sont aussi posés à la création : en mode Express, les changer ensuite ne remplace pas le conteneur en cours. Pour modifier un secret : `az containerapp delete --name rag-api --resource-group rg-rag-nexalis --yes` puis relancer le script. Le script lit `HF_TOKEN` et `LLM_SPACE_ID` dans `.env` et les envoie à Azure comme secrets (rien n'est affiché). Si `API_KEYS` est absent de `.env`, il génère une clé employé et une clé admin. Les abonnements étudiants limitent les régions (`az policy assignment list` indique lesquelles) : `francecentral` est refusée, le déploiement réel utilise `-Location germanywestcentral`. Le script est rejouable : il réutilise ce qui existe déjà.

   À la fin, il affiche les trois valeurs à copier dans GitHub et l'URL de l'application.

4. **Créer le compte de service pour GitHub** (droits limités au groupe de ressources, jamais à l'abonnement) :

   ```powershell
   $sub = az account show --query id -o tsv
   az ad sp create-for-rbac --name sp-rag-nexalis-github --role Contributor `
       --scopes "/subscriptions/$sub/resourceGroups/rg-rag-nexalis" --sdk-auth
   ```

   La commande affiche un JSON : **c'est un secret**. Le copier tel quel dans GitHub (étape suivante), ne pas le coller ailleurs. Si Azure refuse (« insufficient privileges »), c'est que l'abonnement étudiant ne permet pas de créer des applications Entra : demander à l'administrateur du tenant, ou passer par un déploiement local (section 4).

   Le rôle Contributor suffit pour mettre à jour l'application. Pour pousser dans le registre, ajouter aussi :

   ```powershell
   $appId = az ad sp list --display-name sp-rag-nexalis-github --query "[0].appId" -o tsv
   az role assignment create --assignee $appId --role AcrPush `
       --scope (az acr show --name <nom-du-registre> --query id -o tsv)
   ```

5. **Renseigner GitHub** (dépôt > Settings > Secrets and variables > Actions) :

   | Type | Nom | Valeur |
   | --- | --- | --- |
   | Secret | `AZURE_CREDENTIALS` | le JSON de l'étape 4 |
   | Variable | `AZURE_RESOURCE_GROUP` | `rg-rag-nexalis` |
   | Variable | `AZURE_REGISTRY` | le nom du registre affiché par le script |
   | Variable | `AZURE_CONTAINER_APP` | `rag-api` |

## 2. Déployer

**Automatique** : chaque fusion sur `main` lance la CI (`ci.yml`) ; si elle réussit, `deploy.yml` construit l'image, la pousse, met à jour l'application avec la variable `GIT_SHA`, puis attend que `/health` renvoie ce commit. Ce dernier contrôle compte en mode Express : il garantit que c'est bien le nouveau conteneur qui répond, pas l'ancien. Une CI en échec, ou une CI de pull request, ne déploie jamais.

**Manuel** : GitHub > Actions > **Déploiement Azure** > *Run workflow*.

Compter 15 à 25 minutes la première fois (image d'environ 8 Go), beaucoup moins ensuite grâce au cache. L'URL finale est dans les journaux : `https://<application>.<région>.azurecontainerapps.io/ui/`.

L'index (`chroma_db/`) est versionné dans le dépôt et copié dans l'image : si le corpus change, relancer `python -m ingestion.ingest`, committer `chroma_db/` et `data/raw/metadata.json`, puis redéployer.

## 3. Après le déploiement

- **Clés d'API** : l'authentification est active en production. Dans l'interface, bouton clé (en bas du menu) pour saisir la clé employé. Lire les clés générées :

  ```powershell
  az containerapp secret show --name rag-api --resource-group rg-rag-nexalis --secret-name api-keys --query value -o tsv
  ```

- **Space ZeroGPU** : il se met en pause après inactivité. Le relancer avant une démonstration (`python -m scripts.deploy_space --status`). Sans lui, l'API répond mais les questions échouent avec un message clair.
- **MLflow** : chaque question est suivie dans une base SQLite du conteneur (`MLFLOW_TRACKING_URI`, posé par l'image), lue par la page Monitoring. Elle est **éphémère** : elle repart de zéro à chaque déploiement ou redémarrage. Pour la conserver : un serveur MLflow dédié, ou un partage Azure Files monté dans le conteneur.
- **Ajout de documents** : avec la clé admin, la page Corpus permet d'ajouter un PDF, un scan, un Word ou un Markdown, indexé aussitôt (jusqu'à une ou deux minutes pour un scan lu par OCR). Comme la base MLflow, ces ajouts vivent sur le disque du conteneur et disparaissent au déploiement suivant : pour en faire un document permanent, l'ajouter à `data/raw` dans le dépôt, réindexer et committer.
- **Une seule réplique** (`--max-replicas 1`) : la base MLflow et les documents ajoutés sont propres à chaque réplique, deux répliques donneraient deux historiques différents.
- **Journaux** : pas d'espace de journaux (création sans Log Analytics, moins de dépendances et de coûts) ; `az containerapp logs show` ne fonctionne pas en mode Express. Utiliser `/health` et, si besoin, le portail Azure (Journal de la révision).

## 4. Alternative sans compte de service (déploiement depuis votre machine)

Si Azure refuse la création du compte de service, construire et pousser l'image soi-même (Docker Desktop démarré) :

```powershell
az acr login --name <registre>
docker build -t <registre>.azurecr.io/rag-api:manuel .
docker push <registre>.azurecr.io/rag-api:manuel
az containerapp update --name rag-api --resource-group rg-rag-nexalis --image <registre>.azurecr.io/rag-api:manuel
```

## Coûts et arrêt

- L'application garde **1 réplique de 2 vCPU / 4 Go allumée en permanence** (le chargement de BGE-M3 prend 20 à 70 s : un démarrage à froid à chaque question serait inacceptable). C'est plus que l'hypothèse « 10 h par jour » de `docs/estimation_budget.md` ; le tarif est à l'usage, avec une part gratuite mensuelle. Surveiller *Cost Management* dans le portail Azure pour les crédits étudiants.
- Pour limiter la dépense hors démonstration :

  ```powershell
  az containerapp update --name rag-api --resource-group rg-rag-nexalis --min-replicas 0
  ```

  (la première requête suivante attendra le démarrage).
- **Tout supprimer** (application, registre, environnement) :

  ```powershell
  az group delete --name rg-rag-nexalis --yes
  az ad sp delete --id <appId>
  ```
