# Minikube setup script for Windows PowerShell
# Usage: powershell -ExecutionPolicy Bypass -File setup-minikube.ps1

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Minikube Setup for Code Graph Builder" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Check prerequisites
Write-Host "Checking prerequisites..." -ForegroundColor Yellow

$docker = docker --version 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host "[OK] Docker found" -ForegroundColor Green
}
else {
    Write-Host "[ERROR] Docker not found" -ForegroundColor Red
    Write-Host "Please install Docker Desktop first" -ForegroundColor Red
    exit 1
}

$minikube = minikube version 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host "[OK] Minikube found" -ForegroundColor Green
}
else {
    Write-Host "[ERROR] Minikube not found" -ForegroundColor Red
    Write-Host "Please install Minikube first" -ForegroundColor Red
    exit 1
}

Write-Host ""

# Clean if requested
if ($args -contains "--clean") {
    Write-Host "Cleaning up old cluster..." -ForegroundColor Yellow
    minikube delete 2>$null
    Write-Host "[OK] Cluster cleaned" -ForegroundColor Green
    Write-Host ""
}

# Start Minikube
Write-Host "Starting Minikube cluster..." -ForegroundColor Yellow
minikube start `
    --driver=docker `
    --cpus=4 `
    --memory=4096 `
    --disk-size=20g `
    --kubernetes-version=v1.28.0 `
    2>$null

Write-Host "[OK] Minikube started" -ForegroundColor Green
Write-Host ""

# Wait for cluster
Write-Host "Waiting for cluster to be ready..." -ForegroundColor Yellow
Start-Sleep -Seconds 3

# Get cluster info
minikube kubectl -- cluster-info 2>$null | Out-Null

Write-Host "[OK] Cluster is ready" -ForegroundColor Green
Write-Host ""

# Show status
Write-Host "Cluster status:" -ForegroundColor Cyan
minikube status
Write-Host ""

# Configure docker environment
Write-Host "Configuring Docker environment..." -ForegroundColor Yellow
$dockerEnv = minikube docker-env --shell ps1 | Out-String
Invoke-Expression $dockerEnv
Write-Host "[OK] Docker context set to Minikube" -ForegroundColor Green
Write-Host ""

# Build image
Write-Host "Building Docker image in Minikube..." -ForegroundColor Yellow
docker build -t code-graph-builder:latest .
Write-Host "[OK] Image built successfully" -ForegroundColor Green
Write-Host ""

# Verify image
Write-Host "Verifying image..." -ForegroundColor Yellow
$imageCheck = docker images | Select-String "code-graph-builder"
if ($imageCheck) {
    Write-Host "[OK] Image verified" -ForegroundColor Green
    Write-Host $imageCheck -ForegroundColor Green
}
Write-Host ""

# Create namespace
Write-Host "Creating namespace..." -ForegroundColor Yellow
minikube kubectl -- create namespace code-graph --dry-run=client -o yaml | minikube kubectl -- apply -f - 2>$null
Write-Host "[OK] Namespace created" -ForegroundColor Green
Write-Host ""

Write-Host "========================================" -ForegroundColor Green
Write-Host "Setup Complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""

Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host ""
Write-Host "1. Deploy test job:" -ForegroundColor Yellow
Write-Host "   minikube kubectl -- apply -f k8s-minikube.yaml" -ForegroundColor White
Write-Host ""
Write-Host "2. Check job status:" -ForegroundColor Yellow
Write-Host "   minikube kubectl -- get pods -n code-graph" -ForegroundColor White
Write-Host "   minikube kubectl -- logs -f job/code-graph-analysis -n code-graph" -ForegroundColor White
Write-Host ""
Write-Host "3. Access Minikube dashboard:" -ForegroundColor Yellow
Write-Host "   minikube dashboard" -ForegroundColor White
Write-Host ""
Write-Host "4. Stop Minikube:" -ForegroundColor Yellow
Write-Host "   minikube stop" -ForegroundColor White
Write-Host ""
Write-Host "5. Reset Docker environment:" -ForegroundColor Yellow
Write-Host "   & minikube docker-env --unset | Invoke-Expression" -ForegroundColor White
Write-Host ""
