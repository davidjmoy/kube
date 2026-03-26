# deploy/deploy.ps1 — Build, push, and deploy to AKS
# Usage: .\deploy\deploy.ps1
#
# Prerequisites:
#   - az login
#   - kubelogin convert-kubeconfig -l azurecli
#   - Docker running

param(
    [string]$ResourceGroup = "kube",
    [string]$AksName = "damoy-aks",
    [string]$AcrName = "damoyacr",
    [string]$ImageName = "code-graph-chatbot",
    [string]$ImageTag = "latest",
    [string]$Namespace = "code-graph",
    [string]$OpenAIResource = "damoy-openai3",
    [string]$ManagedIdentityName = "code-graph-identity"
)

$ErrorActionPreference = "Stop"
$AcrServer = "$AcrName.azurecr.io"
$FullImage = "$AcrServer/${ImageName}:${ImageTag}"

Write-Host "=== Code Graph Chatbot — AKS Deployment ===" -ForegroundColor Cyan
Write-Host ""

# -----------------------------------------------------------
# Step 1: Build Docker image
# -----------------------------------------------------------
Write-Host "[1/6] Building Docker image..." -ForegroundColor Yellow
docker build -t $FullImage .
if ($LASTEXITCODE -ne 0) { throw "Docker build failed" }
Write-Host "[OK] Image built: $FullImage" -ForegroundColor Green

# -----------------------------------------------------------
# Step 2: Push to ACR
# -----------------------------------------------------------
Write-Host "[2/6] Pushing to ACR..." -ForegroundColor Yellow
az acr login --name $AcrName 2>$null
docker push $FullImage
if ($LASTEXITCODE -ne 0) { throw "Docker push failed" }
Write-Host "[OK] Image pushed" -ForegroundColor Green

# -----------------------------------------------------------
# Step 3: Create Managed Identity for workload identity
# -----------------------------------------------------------
Write-Host "[3/6] Setting up Managed Identity..." -ForegroundColor Yellow

$identity = az identity show --name $ManagedIdentityName --resource-group $ResourceGroup 2>$null | ConvertFrom-Json
if (-not $identity) {
    Write-Host "  Creating managed identity: $ManagedIdentityName"
    $identity = az identity create --name $ManagedIdentityName --resource-group $ResourceGroup | ConvertFrom-Json
    Start-Sleep -Seconds 10  # Wait for AAD propagation
}
$clientId = $identity.clientId
$principalId = $identity.principalId
Write-Host "  Client ID: $clientId"

# Assign Cognitive Services OpenAI User role
$openaiId = az cognitiveservices account show --name $OpenAIResource --resource-group $ResourceGroup --query id -o tsv
$existing = az role assignment list --assignee $principalId --scope $openaiId --query "[?roleDefinitionName=='Cognitive Services OpenAI User']" | ConvertFrom-Json
if ($existing.Count -eq 0) {
    Write-Host "  Assigning Cognitive Services OpenAI User role..."
    az role assignment create `
        --assignee-object-id $principalId `
        --assignee-principal-type ServicePrincipal `
        --role "Cognitive Services OpenAI User" `
        --scope $openaiId 2>$null | Out-Null
    Write-Host "  Role assigned (may take 1-2 min to propagate)"
}
else {
    Write-Host "  Role already assigned"
}
Write-Host "[OK] Managed identity ready" -ForegroundColor Green

# -----------------------------------------------------------
# Step 4: Create federated credential for workload identity
# -----------------------------------------------------------
Write-Host "[4/6] Setting up federated credential..." -ForegroundColor Yellow

$oidcIssuer = az aks show --name $AksName --resource-group $ResourceGroup --query "oidcIssuerProfile.issuerUrl" -o tsv
$fedName = "code-graph-k8s-fed"
$fedExists = az identity federated-credential show --identity-name $ManagedIdentityName --resource-group $ResourceGroup --name $fedName 2>$null
if (-not $fedExists) {
    Write-Host "  Creating federated credential..."
    az identity federated-credential create `
        --identity-name $ManagedIdentityName `
        --resource-group $ResourceGroup `
        --name $fedName `
        --issuer $oidcIssuer `
        --subject "system:serviceaccount:${Namespace}:code-graph-sa" `
        --audiences "api://AzureADTokenExchange" 2>$null | Out-Null
}
else {
    Write-Host "  Federated credential already exists"
}
Write-Host "[OK] Federated credential ready" -ForegroundColor Green

# -----------------------------------------------------------
# Step 5: Apply K8s manifests (substitute client ID)
# -----------------------------------------------------------
Write-Host "[5/6] Deploying to AKS..." -ForegroundColor Yellow

$manifest = Get-Content "deploy/k8s-manifests.yaml" -Raw
$manifest = $manifest.Replace('${MANAGED_IDENTITY_CLIENT_ID}', $clientId)
$manifest = $manifest.Replace("damoyacr.azurecr.io/code-graph-chatbot:latest", $FullImage)

$tempFile = [System.IO.Path]::GetTempFileName() + ".yaml"
$manifest | Set-Content -Path $tempFile -Encoding utf8

kubectl apply -f $tempFile
if ($LASTEXITCODE -ne 0) { throw "kubectl apply failed" }
Write-Host "[OK] Manifests applied" -ForegroundColor Green

# -----------------------------------------------------------
# Step 6: Wait for rollout
# -----------------------------------------------------------
Write-Host "[6/6] Waiting for rollout..." -ForegroundColor Yellow
kubectl rollout status deployment/code-graph-chatbot -n $Namespace --timeout=300s

Write-Host ""
Write-Host "=== Deployment complete! ===" -ForegroundColor Green
Write-Host ""

# Get the external IP
Write-Host "Waiting for external IP..." -ForegroundColor Yellow
for ($i = 0; $i -lt 12; $i++) {
    $ip = kubectl get svc code-graph-chatbot -n $Namespace -o jsonpath="{.status.loadBalancer.ingress[0].ip}" 2>$null
    if ($ip) {
        Write-Host ""
        Write-Host "Chatbot is live at: http://$ip" -ForegroundColor Green
        break
    }
    Write-Host "  Waiting for LoadBalancer IP..." -ForegroundColor Gray
    Start-Sleep -Seconds 10
}

if (-not $ip) {
    Write-Host "LoadBalancer IP not assigned yet. Check with:" -ForegroundColor Yellow
    Write-Host "  kubectl get svc code-graph-chatbot -n $Namespace"
}
