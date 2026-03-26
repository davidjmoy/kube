# Minikube Testing Guide

Complete guide for testing the code-graph-builder locally with Minikube before deploying to AKS.

## Prerequisites

✅ You have:
- Docker Desktop installed
- Minikube installed
- Kubernetes repo at `c:\Users\david\repos\kubernetes`

## Quick Setup (5 minutes)

### 1. Start Minikube

```powershell
# Windows PowerShell
cd c:\Users\david\repos\kube\code-graph-builder
powershell -ExecutionPolicy Bypass -File scripts/setup-minikube.ps1

# Or on Linux/Mac
bash scripts/setup-minikube.sh
```

This will:
- Start a Minikube cluster (4 CPUs, 4GB RAM)
- Build the Docker image locally
- Create a `code-graph` namespace
- Configure Docker to use Minikube

### 2. Verify Setup

```bash
# Check cluster
minikube status

# Check image
docker images | grep code-graph-builder

# Check namespace
minikube kubectl -- get ns
```

## Testing Strategy

### Phase 1: Local CLI Testing (No Kubernetes)

```bash
cd code-graph-builder

# Activate Python environment
python -m venv venv
.\venv\Scripts\activate  # Windows
source venv/bin/activate # Linux/Mac

pip install -r requirements.txt

# Test small analysis
python main.py analyze \
  --repo-root c:\Users\david\repos\kubernetes \
  --pkg-dir pkg/client \
  --output output/graph.json

# Verify output
python main.py analyze-graph --graph output/graph.json

# Try queries
python main.py find-callers --graph output/graph.json --function NewClient
```

**Expected Output:**
- ✅ "Parsed XXX Go files"
- ✅ Graph JSON file created (~5-10MB for pkg/client)
- ✅ Statistics showing functions, types, calls
- ✅ Function query results

**If Issues:**
- Tree-sitter error? → Run `pip install --upgrade tree-sitter tree-sitter-go`
- Out of memory? → Reduce package scope with `--pkg-dir`
- No files parsed? → Check Kubernetes path exists

### Phase 2: Docker Image Testing

```bash
# Build image
docker build -t code-graph-builder:latest .

# Test image locally
docker run --rm \
  -v c:\Users\david\repos\kubernetes:/data/k8s \
  -v output:/output \
  code-graph-builder:latest \
  python main.py analyze \
    --repo-root /data/k8s \
    --pkg-dir pkg/client \
    --output /output/graph-docker.json

# Check output
ls -la output/graph-docker.json
```

**Expected:**
- ✅ Image builds without errors
- ✅ Container runs and completes
- ✅ Output file created with ~same size as local CLI

### Phase 3: Minikube Kubernetes Testing

```bash
# Switch Docker to Minikube daemon
eval $(minikube docker-env)

# Rebuild image in Minikube
docker build -t code-graph-builder:latest .

# Deploy to Minikube
minikube kubectl -- apply -f k8s-minikube.yaml

# Watch deployment
minikube kubectl -- get pods -n code-graph -w

# Check logs
minikube kubectl -- logs -f job/code-graph-analysis -n code-graph

# Access output when complete
minikube kubectl -- exec -it <pod-name> -n code-graph -- bash
cat /output/graph.json
```

## Common Commands

### Cluster Management
```bash
# Start cluster
minikube start --driver=docker --cpus=4 --memory=4096

# Stop cluster
minikube stop

# Delete cluster
minikube delete

# Check status
minikube status

# Get cluster info
minikube kubectl -- cluster-info
```

### Namespace & Resources
```bash
# Create namespace
minikube kubectl -- create namespace code-graph

# List pods
minikube kubectl -- get pods -n code-graph
minikube kubectl -- get pods -n code-graph -o wide

# Describe pod (for debugging)
minikube kubectl -- describe pod <pod-name> -n code-graph

# View logs
minikube kubectl -- logs <pod-name> -n code-graph
minikube kubectl -- logs -f <pod-name> -n code-graph  # Follow

# Execute command in pod
minikube kubectl -- exec -it <pod-name> -n code-graph -- bash
```

### Docker Management
```bash
# Switch to Minikube docker
eval $(minikube docker-env)                    # Linux/Mac
# or in PowerShell:
& minikube docker-env | Invoke-Expression

# Switch back to Docker Desktop
eval $(minikube docker-env --unset)            # Linux/Mac
# or in PowerShell:
& minikube docker-env --unset | Invoke-Expression

# List images in Minikube
docker images

# Build in Minikube
docker build -t code-graph-builder:latest .
```

### Debugging
```bash
# SSH into Minikube VM
minikube ssh

# View Minikube logs
minikube logs

# Increase verbosity
minikube start --loglevel=debug

# Dashboard
minikube dashboard

# Port forwarding
minikube kubectl -- port-forward pod/<pod-name> 8000:8000 -n code-graph
```

## Deployment Manifest Reference

File: `k8s-minikube.yaml` contains:
- **Namespace** - `code-graph`
- **Job** - Analysis job with volume mounts
- **ServiceAccount** - For RBAC
- **Role & RoleBinding** - Minimal permissions
- **Service** - NodePort for API access (port 30000)

## Testing Workflow

### Day 1: Local CLI Verification
```bash
# 1. Extract small k8s package
python main.py analyze \
  --repo-root c:\Users\david\repos\kubernetes \
  --pkg-dir pkg/client \
  --output output/test-1.json

# 2. Verify output
python main.py analyze-graph --graph output/test-1.json

# 3. Try queries
python main.py find-callers --graph output/test-1.json --function NewClient

# 4. Run examples
python examples.py
```

### Day 2: Docker Container Testing
```bash
# 1. Build image
docker build -t code-graph-builder:test .

# 2. Test with volume mounts
docker run --rm \
  -v c:\Users\david\repos\kubernetes:/data/k8s:ro \
  -v c:\temp\output:/output \
  code-graph-builder:test \
  python main.py analyze \
    --repo-root /data/k8s \
    --pkg-dir pkg/api \
    --output /output/graph.json

# 3. Verify persistent output
ls c:\temp\output\
```

### Day 3: Kubernetes Deployment
```bash
# 1. Setup Minikube
powershell -ExecutionPolicy Bypass -File scripts/setup-minikube.ps1

# 2. Deploy
minikube kubectl -- apply -f k8s-minikube.yaml

# 3. Monitor
minikube kubectl -- get pods -n code-graph
minikube kubectl -- logs -f job/code-graph-analysis -n code-graph

# 4. Access results
minikube kubectl -- exec -it <pod> -n code-graph -- bash
cat /output/graph.json | head -100
```

## Troubleshooting

### Pod stuck in Pending
```bash
# Check node resources
minikube kubectl -- top nodes
minikube kubectl -- describe node minikube

# Increase Minikube resources
minikube stop
minikube start --cpus=4 --memory=8192
```

### Out of memory errors
```bash
# Reduce analysis scope
python main.py analyze \
  --repo-root ... \
  --pkg-dir pkg/client  # Smaller than pkg/

# Or increase Minikube memory
minikube delete
minikube start --memory=8192
```

### Image not found
```bash
# Make sure image was built in Minikube context
eval $(minikube docker-env)
docker build -t code-graph-builder:latest .

# Verify
docker images | grep code-graph-builder
```

### Slow analysis
```bash
# Check Minikube performance
minikube logs

# Try with more resources
minikube stop
minikube start --cpus=4 --memory=8192 --disk-size=30g

# Check host machine resources
docker stats  # See Docker Desktop resource usage
```

### Cannot connect to Kubernetes
```bash
# Verify kubectl config
minikube kubectl config view

# Update kubeconfig
minikube update-context

# Verify cluster connectivity
minikube kubectl -- get nodes
```

## Performance Metrics

Typical analysis times (pkg/client):

| Scenario | Time | Memory | Size |
|----------|------|--------|------|
| CLI local | 20-30s | 200MB | 8MB |
| Docker local | 30-40s | 250MB | 8MB |
| K8s Minikube | 40-60s | 300MB | 8MB |

Full Kubernetes analysis:
- Full repo: 8-12 minutes, 2-4GB, 150-300MB JSON

## Next Steps After Testing

1. ✅ Verified locally with CLI
2. ✅ Tested in Docker container
3. ✅ Deployed to Minikube K8s cluster
4. → Deploy to AKS (same manifests, larger resources)
5. → Connect to LLM backend
6. → Scale for production

## AKS Deployment (After Minikube Validation)

```bash
# Create AKS cluster
az aks create --resource-group mygroup --name mycluster --node-count 3

# Get credentials
az aks get-credentials --resource-group mygroup --name mycluster

# Push image to ACR
docker tag code-graph-builder:latest myregistry.azurecr.io/code-graph-builder:v1
docker push myregistry.azurecr.io/code-graph-builder:v1

# Update manifest with ACR image
# Replace "image: code-graph-builder:latest" with ACR URL
# Remove "imagePullPolicy: Never"

# Deploy to AKS
kubectl apply -f k8s-aks.yaml

# Monitor
kubectl get pods -n code-graph
kubectl logs -f job/code-graph-analysis -n code-graph
```

## Resources

- [Minikube Documentation](https://minikube.sigs.k8s.io/)
- [Docker Desktop K8s](https://www.docker.com/products/docker-desktop)
- [kubectl Cheat Sheet](https://kubernetes.io/docs/reference/kubectl/cheatsheet/)
