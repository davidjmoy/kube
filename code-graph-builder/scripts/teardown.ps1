# =============================================================================
# teardown.ps1 — Destroy all costly Azure resources
# =============================================================================
# Tears down everything via terraform destroy.
# The resource group and all resources within it will be deleted.
#
# Usage: .\scripts\teardown.ps1

param(
    [switch]$Force
)

$ErrorActionPreference = "Stop"

Write-Host "=== Code Graph Chatbot — Teardown ===" -ForegroundColor Red
Write-Host ""
Write-Host "This will DESTROY all Azure resources:" -ForegroundColor Yellow
Write-Host "  - AKS cluster (damoy-aks)" -ForegroundColor Yellow
Write-Host "  - Container Registry (damoyacr)" -ForegroundColor Yellow
Write-Host "  - Azure OpenAI (damoy-openai3)" -ForegroundColor Yellow
Write-Host "  - Public IP (codegraph-ip)" -ForegroundColor Yellow
Write-Host "  - Managed Identity (code-graph-identity)" -ForegroundColor Yellow
Write-Host "  - Resource Group (kube)" -ForegroundColor Yellow
Write-Host ""

if (-not $Force) {
    $confirm = Read-Host "Type 'destroy' to confirm"
    if ($confirm -ne "destroy") {
        Write-Host "Aborted." -ForegroundColor Gray
        return
    }
}

Write-Host ""
Write-Host "Running terraform destroy..." -ForegroundColor Yellow
Push-Location terraform
terraform destroy -auto-approve
Pop-Location

Write-Host ""
Write-Host "=== All resources destroyed ===" -ForegroundColor Green
Write-Host ""
Write-Host "To rebuild later:" -ForegroundColor Cyan
Write-Host "  cd terraform; terraform apply" -ForegroundColor White
Write-Host "  cd ..; .\scripts\rebuild.ps1" -ForegroundColor White
