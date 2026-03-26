"""Main CLI application for code graph analysis."""

import click
import json
from pathlib import Path
from typing import Optional

from src.parser import GoCodeParser
from src.graph import CodeGraphSerializer
from src.query import GraphQuery


@click.group()
def cli():
    """Code graph analyzer for Kubernetes source code."""
    pass


@cli.command()
@click.option(
    '--repo-root',
    type=click.Path(exists=True),
    required=True,
    help='Root directory of the Kubernetes repository'
)
@click.option(
    '--pkg-dir',
    type=str,
    default=None,
    help='Specific package directory to analyze (e.g., pkg/client)'
)
@click.option(
    '--output',
    type=click.Path(),
    default='output/code-graph.json',
    help='Output file path for the code graph'
)
@click.option(
    '--stats-output',
    type=click.Path(),
    default='output/graph-stats.json',
    help='Output file path for statistics'
)
def analyze(repo_root: str, pkg_dir: Optional[str], output: str, stats_output: str):
    """Analyze Go source code and build a code graph.
    
    Examples:
        # Analyze specific package
        python main.py analyze --repo-root /path/to/kubernetes --pkg-dir pkg/client
        
        # Analyze entire repository
        python main.py analyze --repo-root /path/to/kubernetes
    """
    click.echo("🔍 Starting code graph analysis...")
    
    try:
        parser = GoCodeParser(repo_root)
        click.echo(f"📁 Analyzing {repo_root}")
        
        if pkg_dir:
            click.echo(f"📂 Focusing on: {pkg_dir}")
        
        # Parse files
        count = parser.parse_directory(pkg_dir, recursive=True)
        click.echo(f"✅ Parsed {count} Go files")
        
        # Get graph
        graph = parser.get_graph()
        stats = graph.stats()
        
        click.echo(f"\n📊 Graph Statistics:")
        click.echo(f"  - Packages: {stats['packages']}")
        click.echo(f"  - Functions: {stats['functions']}")
        click.echo(f"  - Types: {stats['types']}")
        click.echo(f"  - Function calls: {stats['calls']}")
        click.echo(f"  - Avg callers/function: {stats['avg_callers_per_function']:.2f}")
        click.echo(f"  - Avg callees/function: {stats['avg_callees_per_function']:.2f}")
        
        # Save graph
        output_path = Path(output)
        CodeGraphSerializer.save_graph(graph, output_path)
        click.echo(f"\n💾 Graph saved to: {output_path}")
        
        # Save stats
        stats_path = Path(stats_output)
        CodeGraphSerializer.save_stats(graph, stats_path)
        click.echo(f"📈 Stats saved to: {stats_path}")
        
    except Exception as e:
        click.echo(f"❌ Error: {e}", err=True)
        raise


@cli.command()
@click.option(
    '--graph',
    type=click.Path(exists=True),
    required=True,
    help='Path to the code graph JSON file'
)
@click.option(
    '--function',
    type=str,
    required=True,
    help='Function name or full ID to query'
)
@click.option(
    '--depth',
    type=int,
    default=3,
    help='Maximum depth for recursive queries'
)
def find_callers(graph: str, function: str, depth: int):
    """Find all callers of a function.
    
    Examples:
        python main.py find-callers --graph output/code-graph.json --function NewClient
    """
    click.echo(f"🔎 Finding callers of '{function}'...")
    
    try:
        graph_data = CodeGraphSerializer.load_graph(Path(graph))
        
        # For now, simple implementation - user can enhance this
        functions = graph_data['functions']
        
        # Find matching functions
        matches = [
            (fid, f) for fid, f in functions.items()
            if function in fid or f['name'] == function
        ]
        
        if not matches:
            click.echo(f"❌ Function '{function}' not found")
            return
        
        for fid, func in matches:
            click.echo(f"\n✅ Found: {fid}")
            click.echo(f"  - Location: {func['location']['file']}:{func['location']['line']}")
            click.echo(f"  - Callers: {len(func['callers'])}")
            
            if func['callers']:
                click.echo("  - Callers list:")
                for caller_id in func['callers'][:10]:  # Show first 10
                    caller = functions.get(caller_id)
                    if caller:
                        click.echo(f"    • {caller['name']} ({caller_id})")
                if len(func['callers']) > 10:
                    click.echo(f"    ... and {len(func['callers']) - 10} more")
    
    except Exception as e:
        click.echo(f"❌ Error: {e}", err=True)
        raise


@cli.command()
@click.option(
    '--graph',
    type=click.Path(exists=True),
    required=True,
    help='Path to the code graph JSON file'
)
@click.option(
    '--package',
    type=str,
    default=None,
    help='Filter by package name'
)
@click.option(
    '--top-n',
    type=int,
    default=20,
    help='Show top N most-called functions'
)
def analyze_graph(graph: str, package: Optional[str], top_n: int):
    """Analyze and display graph statistics.
    
    Examples:
        python main.py analyze-graph --graph output/code-graph.json
        python main.py analyze-graph --graph output/code-graph.json --package k8s.io/kubernetes/pkg/client
    """
    click.echo("📊 Analyzing code graph...")
    
    try:
        graph_data = CodeGraphSerializer.load_graph(Path(graph))
        metadata = graph_data['metadata']
        functions = graph_data['functions']
        
        click.echo(f"\n📕 Repository: {metadata['repository']}")
        click.echo(f"🕐 Created: {metadata['created_at']}")
        click.echo(f"📦 Total packages: {len(metadata.get('packages', []))}")
        click.echo(f"⚙️  Total functions: {metadata['total_functions']}")
        click.echo(f"🏷️  Total types: {metadata['total_types']}")
        click.echo(f"🔗 Total calls: {metadata['total_calls']}")
        
        # Find most-called functions
        most_called = sorted(
            functions.values(),
            key=lambda f: len(f['callers']),
            reverse=True
        )[:top_n]
        
        click.echo(f"\n🔥 Top {top_n} most-called functions:")
        for i, func in enumerate(most_called, 1):
            if package and package not in func.get('package', ''):
                continue
            click.echo(f"  {i}. {func['name']} - {len(func['callers'])} callers")
            click.echo(f"     Package: {func['package']}")
            click.echo(f"     Location: {func['location']['file']}:{func['location']['line']}")
    
    except Exception as e:
        click.echo(f"❌ Error: {e}", err=True)
        raise


@cli.command()
@click.option(
    '--graph',
    type=click.Path(exists=True),
    required=True,
    help='Path to the code graph JSON file'
)
@click.option(
    '--output',
    type=click.Path(),
    default='output/export.json',
    help='Output file path'
)
def export_json(graph: str, output: str):
    """Export graph in various formats.
    
    Examples:
        python main.py export-json --graph output/code-graph.json
    """
    click.echo(f"📤 Exporting graph...")
    
    try:
        graph_data = CodeGraphSerializer.load_graph(Path(graph))
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, 'w') as f:
            json.dump(graph_data, f, indent=2)
        
        click.echo(f"✅ Exported to: {output_path}")
    
    except Exception as e:
        click.echo(f"❌ Error: {e}", err=True)
        raise


if __name__ == '__main__':
    cli()
