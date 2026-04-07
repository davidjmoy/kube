# =============================================================================
# deploy.ps1 - Build and deploy to Azure Container App
# =============================================================================
# Run from: code-graph-builder/
#
# Prerequisites:
#   - terraform apply completed
#   - az login done
#
# Usage: .\scripts\deploy.ps1
#        .\scripts\deploy.ps1 -ImageTag v4

param(
    [string]$ResourceGroup = "kube",
    [string]$AcrName = "damoyacr",
    [string]$ContainerName = "codegraph-chatbot",
    [string]$ImageTag = "latest"
)

$ErrorActionPreference = "Stop"
$AcrServer = "$AcrName.azurecr.io"
$FullImage = "$AcrServer/code-graph-chatbot:$ImageTag"

Write-Host "=== Code Graph Chatbot - Deploy to Container App ===" -ForegroundColor Cyan
Write-Host "  ACR:       $AcrServer" -ForegroundColor Gray
Write-Host "  Image:     code-graph-chatbot:$ImageTag" -ForegroundColor Gray
Write-Host "  Container: $ContainerName" -ForegroundColor Gray
Write-Host ""

Write-Host "[1/2] Building image in ACR..." -ForegroundColor Yellow
az acr build --registry $AcrName --image "code-graph-chatbot:$ImageTag" --file Dockerfile . --no-logs
Write-Host "  [OK] Image built: $FullImage" -ForegroundColor Green

Write-Host "[2/2] Updating container app..." -ForegroundColor Yellow
az containerapp update --resource-group $ResourceGroup --name $ContainerName --image $FullImage
Write-Host "  [OK] New revision deployed" -ForegroundColor Green

Write-Host ""
Write-Host "Waiting for app to be healthy..." -ForegroundColor Yellow
$fqdn = (az containerapp show --resource-group $ResourceGroup --name $ContainerName --query "properties.configuration.ingress.fqdn" -o tsv)
$url = "https://$fqdn/health"
Write-Host "  Health URL: $url" -ForegroundColor Gray

for ($i = 0; $i -lt 24; $i++) {
    try {
        $response = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 5 -ErrorAction SilentlyContinue
        if ($response.StatusCode -eq 200) {
            Write-Host ""
            Write-Host "=== Deployment complete! ===" -ForegroundColor Green
            Write-Host "  URL: https://$fqdn" -ForegroundColor Green
            Write-Host ""

            $health = $response.Content | ConvertFrom-Json
            Write-Host "  Status:    $($health.status)" -ForegroundColor Gray
            Write-Host "  Functions: $($health.functions)" -ForegroundColor Gray
            exit 0
        }
    }
    catch {
    }

    $elapsed = $i * 10
    Write-Host ("  Waiting... ({0} sec)" -f $elapsed) -ForegroundColor Gray
    Start-Sleep -Seconds 10
}

Write-Host ""
Write-Host "WARNING: App did not respond within 4 minutes." -ForegroundColor Red
Write-Host "Check logs: az containerapp logs show --resource-group $ResourceGroup --name $ContainerName" -ForegroundColor Yellow
