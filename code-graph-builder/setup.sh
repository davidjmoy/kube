#!/bin/bash
# Setup script for code-graph-builder

set -e

echo "🔧 Setting up Code Graph Builder..."

# Check Python version
python_version=$(python3 --version 2>&1 | awk '{print $2}')
echo "✓ Python version: $python_version"

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate || . venv/Scripts/activate

# Install requirements
echo "📥 Installing dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# Create output directory
mkdir -p output

echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "1. Activate the environment:"
echo "   source venv/bin/activate  # Linux/Mac"
echo "   .\\venv\\Scripts\\activate   # Windows"
echo ""
echo "2. Run analysis:"
echo "   python main.py analyze --repo-root /path/to/kubernetes --pkg-dir pkg/client"
echo ""
echo "3. Check examples:"
echo "   python examples.py"
echo ""
