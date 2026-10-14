# Déploiement sur Azure Container Apps

Architecture : l'API (image Docker de ce dépôt : FastAPI, interface `/ui`, index, BGE-M3) tourne sur **Azure Container Apps**. Le LLM reste sur le **Space Hugging Face ZeroGPU** (`LLM_PROVIDER=zerogpu`). L'image est construite par GitHub Actions et stockée dans **Azure Container Registry**.

```
GitHub Actions (manuel) ── build ──> Azure Container Registry ── pull (identifiants du registre) ──> Container Apps ──> Space ZeroGPU
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

   L'environnement Container Apps créé est de type « express » : il refuse l'identité managée, le registre est donc accédé avec ses identifiants administrateur (stockés comme secret de l'application). Le script lit `HF_TOKEN` et `LLM_SPACE_ID` dans `.env` et les envoie à Azure comme secrets (rien n'est affiché). Si `API_KEYS` est absent de `.env`, il génère une clé employé et une clé admin. Les abonnements étudiants limitent les régions (`az policy assignment list` indique lesquelles) : `francecentral` est refusée, le déploiement réel utilise `-Location germanywestcentral`. Le script est rejouable : il réutilise ce qui existe déjà.

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

GitHub > Actions > **Déploiement Azure** > *Run workflow*. Compter 15 à 25 minutes la première fois (image de 7 Go, puis le cache GitHub accélère). Le workflow construit l'image, la pousse, met à jour l'application et attend que `/health` réponde. L'URL finale est dans les journaux : `https://<application>.<région>.azurecontainerapps.io/ui/`.

L'index (`chroma_db/`) est versionné dans le dépôt et copié dans l'image : si le corpus change, relancer `python -m ingestion.ingest`, committer `chroma_db/` et `data/raw/metadata.json`, puis redéployer.

## 3. Après le déploiement

- **Clés d'API** : l'authentification est active en production. Dans l'interface, bouton clé (en bas du menu) pour saisir la clé employé. Lire les clés générées :

  ```powershell
  az containerapp secret show --name rag-api --resource-group rg-rag-nexalis --secret-name api-keys --query value -o tsv
  ```

- **Space ZeroGPU** : il se met en pause après inactivité. Le relancer avant une démonstration (`python -m scripts.deploy_space --status`). Sans lui, l'API répond mais les questions échouent avec un message clair.
- **MLflow** n'est pas déployé (le suivi est désactivé dans l'image) : la page Monitoring l'indique. C'est volontaire, MLflow reste un outil de développement et de soutenance en local.
- **Journaux** : `az containerapp logs show --name rag-api --resource-group rg-rag-nexalis --follow`.

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
