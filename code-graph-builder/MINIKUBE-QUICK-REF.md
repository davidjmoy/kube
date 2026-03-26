# Minikube Testing - Quick Reference

## One-Liner Setup

```powershell
# Windows PowerShell
cd c:\Users\david\repos\kube\code-graph-builder
powershell -ExecutionPolicy Bypass -File scripts/setup-minikube.ps1

# Linux/Mac
cd /path/to/code-graph-builder
bash scripts/setup-minikube.sh
```

## Testing Phases

### Phase 1: Local CLI (No Docker/K8s needed)
```bash
# Install dependencies
python -m venv venv
.\venv\Scripts\activate

# Run analysis
python main.py analyze --repo-root c:\Users\david\repos\kubernetes --pkg-dir pkg/client

# Verify
python main.py analyze-graph --graph output/code-graph.json
```

### Phase 2: Docker Container
```bash
# Build
docker build -t code-graph-builder:test .

# Run
docker run --rm \
  -v c:\Users\david\repos\kubernetes:/data/k8s:ro \
  -v output:/output \
  code-graph-builder:test \
  python main.py analyze --repo-root /data/k8s --pkg-dir pkg/client
```

### Phase 3: Kubernetes (Minikube)
```powershell
# Setup (one time)
powershell -ExecutionPolicy Bypass -File scripts/setup-minikube.ps1

# Deploy
minikube kubectl -- apply -f k8s-minikube.yaml

# Monitor
minikube kubectl -- get pods -n code-graph
minikube kubectl -- logs -f job/code-graph-analysis -n code-graph

# Access results
minikube kubectl -- exec -it <pod-name> -n code-graph -- bash
```

## Essential Commands

| Task | Command |
|------|---------|
| Start Minikube | `minikube start --driver=docker` |
| Stop | `minikube stop` |
| Status | `minikube status` |
| Delete | `minikube delete` |
| Dashboard | `minikube dashboard` |
| Docker env | `eval $(minikube docker-env)` |
| Reset Docker | `eval $(minikube docker-env --unset)` |
| Get pods | `minikube kubectl -- get pods -n code-graph` |
| View logs | `minikube kubectl -- logs -f -n code-graph <pod>` |
| SSH into VM | `minikube ssh` |

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Minikube won't start | `minikube delete` && restart |
| Out of memory | Increase: `minikube start --memory=8192` |
| Image not found | `eval $(minikube docker-env)` && rebuild |
| Pod pending | Check resources: `minikube kubectl -- describe pod <name>` |
| Docker Desktop conflict | Stop Docker, run: `minikube start --driver=docker` |

## File Reference

- **Setup**: `scripts/setup-minikube.ps1` (Windows) or `scripts/setup-minikube.sh` (Linux/Mac)
- **Manifest**: `k8s-minikube.yaml` (optimized for local testing)
- **Guide**: `MINIKUBE-GUIDE.md` (complete documentation)
- **Testing**: `test-workflow.py` (automated tests)

## Next Steps

1. ✅ Run setup script
2. ✅ Deploy test job
3. ✅ Verify job completion
4. → Expand analysis scope
5. → Test API server
6. → Deploy to AKS
