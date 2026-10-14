# Création unique de l'infrastructure Azure : groupe de ressources, registre, Container Apps.
#
# Prérequis : Azure CLI installé et connecté (`az login`), abonnement sélectionné.
# Les secrets (HF_TOKEN, clés d'API) sont lus dans l'environnement ou le fichier .env et envoyés
# directement à Azure : ils ne sont jamais affichés.
#
# Usage (PowerShell) :
#     .\scripts\azure_provision.ps1                       # région francecentral
#     .\scripts\azure_provision.ps1 -Location uksouth     # si la région est refusée par l'abonnement

param(
    [string]$Location = "francecentral",
    [string]$ResourceGroup = "rg-rag-nexalis",
    [string]$Registry = "",          # nom unique mondial ; par défaut : ragnexalis + 6 caractères aléatoires
    [string]$Environment = "cae-rag-nexalis",
    [string]$App = "rag-api"
)

$ErrorActionPreference = "Stop"

function Read-EnvValue([string]$Name) {
    $fromEnv = [Environment]::GetEnvironmentVariable($Name)
    if ($fromEnv) { return $fromEnv }
    if (Test-Path .env) {
        $line = Get-Content .env | Where-Object { $_ -match "^$Name=" } | Select-Object -First 1
        if ($line) { return ($line -split "=", 2)[1].Trim().Trim('"') }
    }
    return ""
}

# Les commandes az renvoient un code de sortie : on s'arrête à la première erreur.
function Invoke-Az {
    # PowerShell 5.1 transforme tout message sur stderr (avertissements d'az) en erreur : seul le code de sortie compte.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & az @args 2>&1 | Out-Host
    $code = $LASTEXITCODE
    $ErrorActionPreference = $previous
    # Seuls les 3 premiers arguments sont cités : les suivants peuvent contenir des secrets.
    if ($code -ne 0) { throw "az $($args[0..2] -join ' ') a échoué (code $code)" }
}

# Résultat texte d'une commande az qui peut échouer (ressource absente) : chaîne vide en cas d'erreur.
function Get-AzValue {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $value = & az @args 2>$null
    $ErrorActionPreference = $previous
    if ($LASTEXITCODE -ne 0) { return "" }
    return ($value -join "`n").Trim()
}
$account = az account show --query "{nom:name, id:id}" -o json 2>$null | ConvertFrom-Json
if (-not $account) { throw "Pas de session Azure : lancez d'abord `az login`." }
Write-Host "Abonnement : $($account.nom)"

$hfToken = Read-EnvValue "HF_TOKEN"
$spaceId = Read-EnvValue "LLM_SPACE_ID"
if (-not $hfToken -or -not $spaceId) { throw "HF_TOKEN et LLM_SPACE_ID doivent être définis (.env ou environnement)." }

# Clés d'API : si API_KEYS n'est pas fourni, on en génère deux (employé et admin).
$apiKeys = Read-EnvValue "API_KEYS"
$generated = $false
if (-not $apiKeys) {
    $bytes = New-Object byte[] 24
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    $rng.GetBytes($bytes); $employee = [Convert]::ToBase64String($bytes) -replace '[^A-Za-z0-9]', 'x'
    $rng.GetBytes($bytes); $admin = [Convert]::ToBase64String($bytes) -replace '[^A-Za-z0-9]', 'x'
    $apiKeys = "${employee}:employe,${admin}:admin"
    $generated = $true
}

# Le script peut être relancé : ce qui existe déjà dans le groupe de ressources est réutilisé.
if (-not $Registry) {
    $existing = Get-AzValue acr list --resource-group $ResourceGroup --query "[0].name" -o tsv
    if ($existing) { $Registry = $existing }
    else { $Registry = "ragnexalis" + (-join ((97..122) | Get-Random -Count 6 | ForEach-Object { [char]$_ })) }
}

# Un abonnement neuf (étudiant notamment) n'a pas encore activé ces services.
Write-Host "0/5 Activation des services Azure nécessaires (quelques minutes la première fois)"
foreach ($namespace in "Microsoft.ContainerRegistry", "Microsoft.App", "Microsoft.OperationalInsights") {
    Invoke-Az provider register --namespace $namespace --wait
}

Write-Host "1/5 Groupe de ressources $ResourceGroup ($Location)"
Invoke-Az group create --name $ResourceGroup --location $Location --output none

Write-Host "2/5 Registre $Registry (Basic)"
if (-not (Get-AzValue acr show --name $Registry --query name -o tsv)) {
    Invoke-Az acr create --name $Registry --resource-group $ResourceGroup --sku Basic --location $Location --output none
}

Write-Host "3/5 Environnement Container Apps $Environment"
if (-not (Get-AzValue containerapp env show --name $Environment --resource-group $ResourceGroup --query name -o tsv)) {
    Invoke-Az containerapp env create --name $Environment --resource-group $ResourceGroup --location $Location --output none
}

Write-Host "4/5 Application $App (image de démarrage, remplacée par le workflow)"
if (-not (Get-AzValue containerapp show --name $App --resource-group $ResourceGroup --query name -o tsv)) {
    Invoke-Az containerapp create --name $App --resource-group $ResourceGroup --environment $Environment `
        --image mcr.microsoft.com/k8se/quickstart:latest --target-port 7860 --ingress external `
        --cpu 2 --memory 4Gi --min-replicas 1 --max-replicas 2 --output none
}

Write-Host "5/5 Accès au registre, secrets et variables"
# Les environnements Container Apps récents n'acceptent pas l'identité managée pour le registre :
# on utilise le compte administrateur du registre (identifiants stockés comme secret de l'application).
Invoke-Az acr update --name $Registry --admin-enabled true --output none
$acrUser = az acr credential show --name $Registry --query username -o tsv
$acrPassword = az acr credential show --name $Registry --query "passwords[0].value" -o tsv
Invoke-Az containerapp registry set --name $App --resource-group $ResourceGroup `
    --server "$Registry.azurecr.io" --username $acrUser --password $acrPassword --output none

# Clés d'API déjà présentes (relance du script) : on ne les régénère pas.
$secretNames = az containerapp secret list --name $App --resource-group $ResourceGroup --query "[].name" -o tsv
if (($secretNames -contains "api-keys") -and $generated) {
    $generated = $false
    Invoke-Az containerapp secret set --name $App --resource-group $ResourceGroup --secrets "hf-token=$hfToken" --output none
} else {
    Invoke-Az containerapp secret set --name $App --resource-group $ResourceGroup `
        --secrets "hf-token=$hfToken" "api-keys=$apiKeys" --output none
}
Invoke-Az containerapp update --name $App --resource-group $ResourceGroup --set-env-vars `
    "ENVIRONMENT=production" "LLM_PROVIDER=zerogpu" "LLM_SPACE_ID=$spaceId" `
    "HF_TOKEN=secretref:hf-token" "API_KEYS=secretref:api-keys" --output none

$fqdn = az containerapp show --name $App --resource-group $ResourceGroup --query properties.configuration.ingress.fqdn -o tsv

Write-Host ""
Write-Host "Infrastructure prête."
Write-Host "  Registre : $Registry.azurecr.io"
Write-Host "  URL      : https://$fqdn/ui/ (en attendant le premier déploiement, c'est l'image de démarrage)"
Write-Host ""
Write-Host "À renseigner dans GitHub (Settings > Secrets and variables > Actions > Variables) :"
Write-Host "  AZURE_RESOURCE_GROUP = $ResourceGroup"
Write-Host "  AZURE_REGISTRY       = $Registry"
Write-Host "  AZURE_CONTAINER_APP  = $App"
if ($generated) {
    Write-Host ""
    Write-Host "Des clés d'API ont été générées et stockées dans Azure (secret api-keys). Pour les lire :"
    Write-Host "  az containerapp secret show --name $App --resource-group $ResourceGroup --secret-name api-keys --query value -o tsv"
}
