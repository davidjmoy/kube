#!/bin/bash
# Test deployment to Minikube

set -e

echo "🚀 Deploying code-graph-builder to Minikube..."

# Check if image exists
echo "📋 Checking for Docker image..."
docker images | grep code-graph-builder || {
    echo "❌ Image not found. Run setup-minikube.sh first"
    exit 1
}

# Update deployment YAML to use local image
echo "📝 Creating deployment manifest..."
cat > /tmp/deployment-test.yaml << 'EOF'
apiVersion: v1
kind: ConfigMap
metadata:
  name: analyzer-config
  namespace: code-graph
data:
  repo-url: "https://github.com/kubernetes/kubernetes.git"
  analysis-package: "pkg/client"

---
apiVersion: batch/v1
kind: Job
metadata:
  name: code-graph-analysis-test
  namespace: code-graph
spec:
  backoffLimit: 1
  activeDeadlineSeconds: 1800  # 30 minutes timeout
  template:
    spec:
      containers:
      - name: analyzer
        image: code-graph-builder:latest
        imagePullPolicy: Never  # Use local image
        command: 
          - python
          - main.py
          - analyze
          - --repo-root
          - /data/kubernetes
          - --pkg-dir
          - pkg/client
          - --output
          - /output/graph.json
          - --stats-output
          - /output/stats.json
        volumeMounts:
        - name: kubernetes-source
          mountPath: /data/kubernetes
        - name: output
          mountPath: /output
        resources:
          requests:
            memory: "512Mi"
            cpu: "500m"
          limits:
            memory: "2Gi"
            cpu: "2"
      volumes:
      - name: kubernetes-source
        emptyDir: {}
      - name: output
        emptyDir: {}
      restartPolicy: Never

---
apiVersion: v1
kind: Service
metadata:
  name: graph-api
  namespace: code-graph
spec:
  selector:
    app: graph-api
  ports:
  - protocol: TCP
    port: 8000
    targetPort: 8000
  type: NodePort
EOF

# Create namespace if not exists
echo "📦 Creating namespace..."
minikube kubectl -- create namespace code-graph --dry-run=client -o yaml | minikube kubectl -- apply -f - 2>/dev/null || true

# Deploy
echo "🚀 Deploying to cluster..."
minikube kubectl -- apply -f /tmp/deployment-test.yaml

# Wait a moment for pod to start
sleep 2

# Show status
echo ""
echo "📊 Deployment status:"
minikube kubectl -- get pods -n code-graph -w &
WATCH_PID=$!
sleep 5
kill $WATCH_PID 2>/dev/null || true

echo ""
echo "📋 Full pod details:"
minikube kubectl -- describe pod -n code-graph -l batch.kubernetes.io/job-name=code-graph-analysis-test 2>/dev/null || echo "Pod not yet created"

echo ""
echo "✅ Deployment submitted!"
echo ""
echo "Monitor with:"
echo "  minikube kubectl -- logs -f job/code-graph-analysis-test -n code-graph"
echo ""
echo "View results:"
echo "  minikube kubectl -- exec -it <pod-name> -n code-graph -- cat /output/graph.json"
