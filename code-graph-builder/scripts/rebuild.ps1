# =============================================================================
# rebuild.ps1 — Rebuild and deploy after terraform apply
# =============================================================================
# Run from: code-graph-builder/
#
# Prerequisites:
#   - terraform apply completed
#   - az login done
#   - Docker running (or use ACR build)
#
# Usage: .\scripts\rebuild.ps1

param(
    [string]$ResourceGroup = "kube",
    [string]$AksName = "damoy-aks",
    [string]$AcrName = "damoyacr",
    [string]$ImageTag = "v3",
    [string]$AuthUser = $env:AUTH_USERNAME,
    [string]$AuthPass = $env:AUTH_PASSWORD
)

# Load .env if present
$envFile = Join-Path $PSScriptRoot "../.env"
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        if ($_ -match '^([^#=]+)=(.*)$') {
            [System.Environment]::SetEnvironmentVariable($Matches[1].Trim(), $Matches[2].Trim(), 'Process')
        }
    }
    if (-not $AuthUser) { $AuthUser = $env:AUTH_USERNAME }
    if (-not $AuthPass) { $AuthPass = $env:AUTH_PASSWORD }
}

if (-not $AuthUser -or -not $AuthPass) {
    Write-Error "AUTH_USERNAME and AUTH_PASSWORD must be set in .env or passed as -AuthUser/-AuthPass"
    exit 1
}

$ErrorActionPreference = "Stop"
$AcrServer = "$AcrName.azurecr.io"
$FullImage = "$AcrServer/code-graph-chatbot:$ImageTag"

Write-Host "=== Code Graph Chatbot — Rebuild ===" -ForegroundColor Cyan

# 1. Build image in ACR
Write-Host "[1/5] Building image in ACR..." -ForegroundColor Yellow
az acr build --registry $AcrName --image "code-graph-chatbot:$ImageTag" --file Dockerfile . --no-logs
Write-Host "[OK] Image built: $FullImage" -ForegroundColor Green

# 2. Get AKS credentials
Write-Host "[2/5] Getting AKS credentials..." -ForegroundColor Yellow
az aks get-credentials --resource-group $ResourceGroup --name $AksName --overwrite-existing
kubelogin convert-kubeconfig -l azurecli
Write-Host "[OK] kubectl configured" -ForegroundColor Green

# 3. Get managed identity client ID from terraform
Write-Host "[3/5] Reading terraform outputs..." -ForegroundColor Yellow
Push-Location terraform
$clientId = (terraform output -raw managed_identity_client_id)
Pop-Location
Write-Host "  Client ID: $clientId" -ForegroundColor Gray

# 4. Apply K8s manifests
Write-Host "[4/5] Deploying to AKS..." -ForegroundColor Yellow
$manifest = Get-Content "deploy/k8s-manifests.yaml" -Raw
$manifest = $manifest.Replace('${MANAGED_IDENTITY_CLIENT_ID}', $clientId)
$tempFile = [System.IO.Path]::GetTempFileName() + ".yaml"
$manifest | Set-Content -Path $tempFile -Encoding utf8
kubectl apply -f $tempFile

# Create auth secret
kubectl create secret generic codegraph-auth -n code-graph `
    --from-literal=username=$AuthUser `
    --from-literal=password=$AuthPass `
    --dry-run=client -o yaml | kubectl apply -f -

# Wait for rollout
Write-Host "[5/5] Waiting for rollout..." -ForegroundColor Yellow
kubectl rollout status deployment/code-graph-chatbot -n code-graph --timeout=300s

# Get external IP
Write-Host ""
Write-Host "=== Deployment complete! ===" -ForegroundColor Green
for ($i = 0; $i -lt 12; $i++) {
    $ip = kubectl get svc code-graph-chatbot -n code-graph -o jsonpath="{.status.loadBalancer.ingress[0].ip}" 2>$null
    if ($ip) {
        Write-Host "Chatbot live at: http://$ip (user: $AuthUser)" -ForegroundColor Green
        break
    }
    Write-Host "  Waiting for IP..." -ForegroundColor Gray
    Start-Sleep -Seconds 10
}
