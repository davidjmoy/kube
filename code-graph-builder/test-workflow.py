#!/usr/bin/env python3
"""
Comprehensive local testing workflow for code-graph-builder.
Tests: CLI → Docker → Kubernetes
"""

import subprocess
import json
import sys
import time
from pathlib import Path

class Color:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    CYAN = '\033[96m'
    END = '\033[0m'

def print_section(title):
    print(f"\n{Color.CYAN}{'='*60}{Color.END}")
    print(f"{Color.CYAN}{title.center(60)}{Color.END}")
    print(f"{Color.CYAN}{'='*60}{Color.END}\n")

def print_success(msg):
    print(f"{Color.GREEN}✅ {msg}{Color.END}")

def print_error(msg):
    print(f"{Color.RED}❌ {msg}{Color.END}")

def print_warning(msg):
    print(f"{Color.YELLOW}⚠️  {msg}{Color.END}")

def run_cmd(cmd, check=True, capture=False):
    """Run a shell command."""
    try:
        if capture:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, check=check)
            return result.stdout.strip()
        else:
            subprocess.run(cmd, shell=True, check=check)
            return True
    except subprocess.CalledProcessError as e:
        print_error(f"Command failed: {cmd}")
        if e.output:
            print(e.output)
        return False

def check_prerequisites():
    """Check if Docker and Minikube are installed."""
    print_section("Checking Prerequisites")
    
    docker = run_cmd("docker --version", capture=True)
    if docker:
        print_success(f"Docker: {docker}")
    else:
        print_error("Docker not found. Install Docker Desktop first.")
        return False
    
    minikube = run_cmd("minikube version", capture=True)
    if minikube:
        print_success(f"Minikube found")
    else:
        print_error("Minikube not found. Install Minikube first.")
        return False
    
    return True

def phase1_cli_testing():
    """Phase 1: Test CLI locally."""
    print_section("Phase 1: Local CLI Testing")
    
    # Check Python environment
    print("🔍 Checking Python environment...")
    if not Path("venv").exists():
        print_warning("Virtual environment not found, creating...")
        run_cmd("python -m venv venv")
    
    # Install dependencies
    print("📥 Installing dependencies...")
    run_cmd("venv\\Scripts\\pip install -r requirements.txt" if sys.platform == "win32" 
            else "venv/bin/pip install -r requirements.txt")
    
    # Run analysis
    print("\n🔍 Running code graph analysis (pkg/client)...")
    python_cmd = "venv\\Scripts\\python" if sys.platform == "win32" else "venv/bin/python"
    
    result = run_cmd(
        f'{python_cmd} main.py analyze '
        '--repo-root c:\\Users\\david\\repos\\kubernetes '
        '--pkg-dir pkg/client '
        '--output output/test-cli.json '
        '--stats-output output/test-cli-stats.json'
    )
    
    if not result:
        print_error("CLI analysis failed")
        return False
    
    # Verify output
    if Path("output/test-cli.json").exists():
        print_success("Graph JSON created")
        
        # Check size and content
        with open("output/test-cli.json") as f:
            graph = json.load(f)
            funcs = len(graph.get('functions', {}))
            types = len(graph.get('types', {}))
            calls = len(graph.get('calls', {}))
            print(f"  📊 Functions: {funcs}, Types: {types}, Calls: {calls}")
    else:
        print_error("Graph JSON not created")
        return False
    
    # Test queries
    print("\n🔍 Testing queries...")
    run_cmd(f'{python_cmd} main.py analyze-graph --graph output/test-cli.json --top-n 5')
    
    print_success("Phase 1 complete: CLI testing passed")
    return True

def phase2_docker_testing():
    """Phase 2: Test Docker container."""
    print_section("Phase 2: Docker Container Testing")
    
    # Build image
    print("🏗️  Building Docker image...")
    if not run_cmd("docker build -t code-graph-builder:test ."):
        print_error("Docker build failed")
        return False
    print_success("Docker image built")
    
    # Run in container
    print("\n🐳 Running analysis in Docker container...")
    output_dir = Path("output/docker-test").absolute()
    output_dir.mkdir(exist_ok=True)
    
    run_cmd(
        f'docker run --rm '
        '-v c:\\Users\\david\\repos\\kubernetes:/data/k8s:ro '
        f'-v {output_dir}:/output '
        'code-graph-builder:test '
        'python main.py analyze '
        '--repo-root /data/k8s '
        '--pkg-dir pkg/client '
        '--output /output/graph.json'
    )
    
    # Verify output
    if (output_dir / "graph.json").exists():
        print_success("Docker container execution successful")
    else:
        print_error("Docker container did not produce output")
        return False
    
    print_success("Phase 2 complete: Docker testing passed")
    return True

def phase3_minikube_testing():
    """Phase 3: Test Kubernetes deployment."""
    print_section("Phase 3: Minikube Kubernetes Testing")
    
    # Check Minikube status
    status = run_cmd("minikube status", capture=True)
    if "Running" not in status:
        print("🎯 Starting Minikube...")
        run_cmd("minikube start --driver=docker --cpus=4 --memory=4096")
    else:
        print_success("Minikube is running")
    
    # Switch to Minikube Docker
    print("\n🐳 Switching Docker context to Minikube...")
    if sys.platform == "win32":
        # PowerShell version for Windows
        print_warning("Windows detected - skipping Docker env switch (manual step needed)")
        print("Run in PowerShell: & minikube docker-env | Invoke-Expression")
    else:
        run_cmd("eval $(minikube docker-env)")
    
    # Build image in Minikube
    print("\n🏗️  Building image in Minikube...")
    run_cmd("docker build -t code-graph-builder:latest .")
    print_success("Image built in Minikube")
    
    # Create namespace
    print("\n📦 Creating namespace...")
    run_cmd("minikube kubectl -- create namespace code-graph --dry-run=client -o yaml | minikube kubectl -- apply -f -")
    print_success("Namespace created")
    
    # Deploy
    print("\n🚀 Deploying to Minikube...")
    run_cmd("minikube kubectl -- apply -f k8s-minikube.yaml")
    print_success("Deployment submitted")
    
    # Monitor job
    print("\n⏳ Waiting for job to complete...")
    time.sleep(3)
    
    # Show status
    run_cmd("minikube kubectl -- get pods -n code-graph")
    
    print(f"\n{Color.YELLOW}Monitor job with:{Color.END}")
    print(f"  minikube kubectl -- logs -f job/code-graph-analysis -n code-graph")
    
    print(f"\n{Color.YELLOW}View results with:{Color.END}")
    print(f"  minikube kubectl -- exec -it <pod-name> -n code-graph -- cat /output/graph.json")
    
    print_success("Phase 3 complete: Deployment submitted")
    return True

def main():
    """Run complete testing workflow."""
    print(f"\n{Color.GREEN}")
    print("╔" + "="*58 + "╗")
    print("║" + "Code Graph Builder - Local Testing Workflow".center(58) + "║")
    print("╚" + "="*58 + "╝")
    print(f"{Color.END}\n")
    
    # Prerequisites
    if not check_prerequisites():
        sys.exit(1)
    
    # Test phases
    phases = [
        ("Local CLI", phase1_cli_testing),
        ("Docker Container", phase2_docker_testing),
        ("Kubernetes (Minikube)", phase3_minikube_testing),
    ]
    
    results = []
    for name, phase_func in phases:
        try:
            success = phase_func()
            results.append((name, success))
            if not success:
                print_warning(f"Phase failed, continuing to next...")
                time.sleep(1)
        except Exception as e:
            print_error(f"Phase error: {e}")
            results.append((name, False))
    
    # Summary
    print_section("Testing Summary")
    for phase_name, success in results:
        status = "✅ PASSED" if success else "❌ FAILED"
        print(f"{phase_name:.<40} {status}")
    
    all_passed = all(success for _, success in results)
    
    if all_passed:
        print_success("All testing phases completed successfully!")
        print(f"\n{Color.GREEN}Next steps:{Color.END}")
        print("1. Code analysis works locally")
        print("2. Docker container works")
        print("3. Kubernetes deployment is running")
        print("4. Ready to:")
        print("   - Analyze more packages")
        print("   - Test API server (see QUICKSTART.md)")
        print("   - Deploy to AKS")
    else:
        print_error("Some phases failed. Review output above.")
        sys.exit(1)

if __name__ == "__main__":
    main()
