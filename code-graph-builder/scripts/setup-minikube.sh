#!/bin/bash
# Minikube setup and testing script for code-graph-builder

set -e

echo "🚀 Setting up Minikube cluster for code-graph-builder testing..."
echo ""

# Check prerequisites
echo "✓ Checking prerequisites..."
docker --version > /dev/null 2>&1 || { echo "❌ Docker not found"; exit 1; }
minikube version > /dev/null 2>&1 || { echo "❌ Minikube not found"; exit 1; }

# Delete existing cluster if requested
if [ "$1" == "--clean" ]; then
    echo "🧹 Cleaning up old Minikube cluster..."
    minikube delete 2>/dev/null || true
    echo "✓ Cluster cleaned"
fi

# Start Minikube
echo ""
echo "🎯 Starting Minikube..."
minikube start \
    --driver=docker \
    --cpus=4 \
    --memory=4096 \
    --disk-size=20g \
    --kubernetes-version=v1.28.0 \
    || true  # Continue even if already running

# Wait for cluster to be ready
echo "⏳ Waiting for cluster to be ready..."
minikube kubectl -- cluster-info

echo ""
echo "✓ Minikube is running"
minikube status

# Configure docker to use minikube's docker daemon
echo ""
echo "🐳 Configuring Docker to use Minikube's daemon..."
eval $(minikube docker-env)
echo "✓ Docker is now pointing to Minikube"

# Build the image using Minikube's docker
echo ""
echo "🏗️  Building Docker image in Minikube..."
docker build -t code-graph-builder:latest ..
echo "✓ Image built successfully"

# Verify image
echo ""
echo "📋 Verifying image..."
docker images | grep code-graph-builder

# Create namespace for testing
echo ""
echo "📦 Creating test namespace..."
minikube kubectl -- create namespace code-graph --dry-run=client -o yaml | minikube kubectl -- apply -f -
echo "✓ Namespace created"

echo ""
echo "✅ Minikube setup complete!"
echo ""
echo "Next steps:"
echo "1. Deploy a test job:"
echo "   minikube kubectl -- apply -f ../k8s-deployment.yaml"
echo ""
echo "2. Check job status:"
echo "   minikube kubectl -- get pods"
echo "   minikube kubectl -- logs job/code-graph-analysis"
echo ""
echo "3. Access Minikube dashboard:"
echo "   minikube dashboard"
echo ""
echo "4. Stop Minikube:"
echo "   minikube stop"
echo ""
echo "5. Reset Docker env (exit Minikube context):"
echo "   eval \$(minikube docker-env --unset)"
echo ""
