# Streaming Chatbot Setup Guide

Complete guide to run the Kubernetes Code Assistant chatbot with streaming responses.

## Architecture

```
Frontend (React)              Backend (FastAPI)              Azure OpenAI
    ↓                              ↓                              ↓
 Chat UI ←→ SSE Stream ←→ Streaming Handler ←→ Azure OpenAI API
                              (GPT-4o)
```

## Prerequisites

- Python 3.9+
- Node.js 16+
- Azure OpenAI API key and deployment
- Generated code graph (`output/code-graph.json`)

## Backend Setup

### 1. Install Dependencies

```bash
cd code-graph-builder
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

pip install -r requirements.txt
```

### 2. Configure Azure OpenAI

Create `.env` file:

```
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_KEY=your-api-key
AZURE_OPENAI_API_VERSION=2024-02-15-preview
AZURE_DEPLOYMENT_NAME=gpt-4o
GRAPH_PATH=output/code-graph.json
MAX_CONTEXT_ITEMS=10
MAX_TOKENS=2000
```

### 3. Generate Code Graph

```bash
python main.py analyze \
  --repo-root /path/to/kubernetes \
  --pkg-dir pkg/client \
  --output output/code-graph.json
```

### 4. Start Backend

```bash
uvicorn src.chatbot_service:app --reload --port 8000
```

Visit: http://localhost:8000/docs

## Frontend Setup

### 1. Install Dependencies

```bash
cd frontend
npm install
```

### 2. Start Development Server

```bash
npm start
```

Opens: http://localhost:3000

## Running Together

### Two Terminals

**Terminal 1:**
```bash
cd code-graph-builder
source venv/bin/activate
uvicorn src.chatbot_service:app --port 8000
```

**Terminal 2:**
```bash
cd frontend
npm start
```

### Docker Compose

```bash
docker-compose -f docker-compose.local.yml up
```

- Frontend: http://localhost:3000
- Backend: http://localhost:8000

## Testing

### Backend Endpoints

```bash
# Health
curl http://localhost:8000/health

# Search
curl "http://localhost:8000/graph/search?query=NewClient"

# Chat (non-streaming)
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What does NewClient do?"}'
```

### Frontend

1. Open http://localhost:3000
2. Type questions about Kubernetes
3. Watch responses stream in real-time
4. See code references appear

## Example Questions

- "What does NewClient function do?"
- "Who calls the kubelet?"
- "What are the most critical functions?"
- "How does the scheduler work?"
- "What types are used in the API?"

## Deployment to AKS

### 1. Build Images

```bash
# Backend
docker build -t myregistry.azurecr.io/code-graph-backend:v1 .

# Frontend
docker build -t myregistry.azurecr.io/code-graph-frontend:v1 frontend/

# Push
docker push myregistry.azurecr.io/code-graph-backend:v1
docker push myregistry.azurecr.io/code-graph-frontend:v1
```

### 2. Update Manifests

Create `k8s-chatbot.yaml`:

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: code-graph

---
apiVersion: v1
kind: ConfigMap
metadata:
  name: backend-config
  namespace: code-graph
data:
  GRAPH_PATH: /data/graph/code-graph.json
  MAX_CONTEXT_ITEMS: "10"
  MAX_TOKENS: "2000"

---
apiVersion: v1
kind: Secret
metadata:
  name: azure-openai
  namespace: code-graph
type: Opaque
stringData:
  AZURE_OPENAI_ENDPOINT: https://your.openai.azure.com/
  AZURE_OPENAI_KEY: your-key
  AZURE_OPENAI_API_VERSION: 2024-02-15-preview
  AZURE_DEPLOYMENT_NAME: gpt-4o

---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: backend
  namespace: code-graph
spec:
  replicas: 2
  selector:
    matchLabels:
      app: backend
  template:
    metadata:
      labels:
        app: backend
    spec:
      containers:
      - name: backend
        image: myregistry.azurecr.io/code-graph-backend:v1
        ports:
        - containerPort: 8000
        envFrom:
        - configMapRef:
            name: backend-config
        - secretRef:
            name: azure-openai
        volumeMounts:
        - name: graph-data
          mountPath: /data/graph
        resources:
          requests:
            memory: "512Mi"
            cpu: "500m"
          limits:
            memory: "2Gi"
            cpu: "2"
      volumes:
      - name: graph-data
        configMap:
          name: graph-data

---
apiVersion: v1
kind: Service
metadata:
  name: backend
  namespace: code-graph
spec:
  selector:
    app: backend
  ports:
  - port: 8000
    targetPort: 8000
  type: ClusterIP

---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: frontend
  namespace: code-graph
spec:
  replicas: 2
  selector:
    matchLabels:
      app: frontend
  template:
    metadata:
      labels:
        app: frontend
    spec:
      containers:
      - name: frontend
        image: myregistry.azurecr.io/code-graph-frontend:v1
        ports:
        - containerPort: 3000
        resources:
          requests:
            memory: "256Mi"
            cpu: "250m"
          limits:
            memory: "512Mi"
            cpu: "1"

---
apiVersion: v1
kind: Service
metadata:
  name: frontend
  namespace: code-graph
spec:
  selector:
    app: frontend
  ports:
  - port: 80
    targetPort: 3000
  type: LoadBalancer
```

### 3. Deploy

```bash
kubectl apply -f k8s-chatbot.yaml
```

### 4. Monitor

```bash
kubectl get pods -n code-graph
kubectl logs -f deploy/backend -n code-graph
```

## Troubleshooting

### Backend won't start
- Check `.env` file exists
- Verify Azure OpenAI credentials
- Check `code-graph.json` exists

### Frontend can't connect
- Ensure backend is running on port 8000
- Check proxy in `package.json`
- Check CORS settings

### Streaming stops
- Check backend logs: `uvicorn` console
- Verify Azure OpenAI API quota
- Check network connection

### Out of memory
- Reduce `MAX_CONTEXT_ITEMS`
- Reduce `MAX_TOKENS`
- Use smaller code graph
