"""Example: Using the code graph programmatically for AI/chatbot backend.

This demonstrates how to use the code graph in a backend system
for answering questions about Kubernetes code.
"""

from pathlib import Path
from src.graph import CodeGraphSerializer
from src.query import GraphQuery


def example_basic_usage():
    """Example 1: Load graph and find callers."""
    print("=" * 60)
    print("Example 1: Finding Callers")
    print("=" * 60)
    
    # Load previously generated graph
    graph_path = Path("output/code-graph.json")
    if not graph_path.exists():
        print("❌ Graph file not found. Run analyze first:")
        print("   python main.py analyze --repo-root /path/to/k8s --pkg-dir pkg/client")
        return
    
    graph_data = CodeGraphSerializer.load_graph(graph_path)
    functions = graph_data['functions']
    
    # Find a specific function
    target_function = "NewClient"
    
    print(f"\n🔍 Searching for functions named '{target_function}'...")
    
    matches = [
        (fid, func) for fid, func in functions.items()
        if func['name'] == target_function
    ]
    
    if not matches:
        print(f"❌ No function found with name '{target_function}'")
        return
    
    for fid, func in matches:
        print(f"\n✅ Found: {func['name']}")
        print(f"   ID: {fid}")
        print(f"   Location: {func['location']['file']}:{func['location']['line']}")
        print(f"   Direct callers: {len(func['callers'])}")
        
        if func['callers']:
            print("\n   Direct Callers:")
            for caller_id in func['callers'][:5]:
                caller = functions.get(caller_id)
                if caller:
                    print(f"     • {caller['name']} at {caller['location']['file']}:{caller['location']['line']}")


def example_query_interface():
    """Example 2: Using the query interface for complex analysis."""
    print("\n" + "=" * 60)
    print("Example 2: Complex Query Interface")
    print("=" * 60)
    
    graph_path = Path("output/code-graph.json")
    if not graph_path.exists():
        print("Graph not found. Run analyze first.")
        return
    
    graph_data = CodeGraphSerializer.load_graph(graph_path)
    
    # Extract metadata
    metadata = graph_data['metadata']
    print(f"\n📊 Graph Overview:")
    print(f"   Repository: {metadata['repository']}")
    print(f"   Created: {metadata['created_at']}")
    print(f"   Total functions: {metadata['total_functions']}")
    print(f"   Total types: {metadata['total_types']}")
    print(f"   Total calls: {metadata['total_calls']}")


def example_chatbot_context():
    """Example 3: Building context for chatbot answers.
    
    This shows how to collect context about a function
    for feeding into an LLM to answer questions.
    """
    print("\n" + "=" * 60)
    print("Example 3: Building Chatbot Context")
    print("=" * 60)
    
    graph_path = Path("output/code-graph.json")
    if not graph_path.exists():
        print("Graph not found.")
        return
    
    graph_data = CodeGraphSerializer.load_graph(graph_path)
    functions = graph_data['functions']
    types = graph_data['types']
    
    # Example: User asks "What does NewClient do?"
    target_name = "NewClient"
    
    matching_funcs = [
        (fid, f) for fid, f in functions.items()
        if f['name'] == target_name
    ]
    
    if not matching_funcs:
        print(f"Function '{target_name}' not found.")
        return
    
    func_id, func = matching_funcs[0]
    
    # Build context
    context = {
        "question": f"What does {target_name} do?",
        "function_info": {
            "name": func['name'],
            "signature": func['signature'],
            "package": func['package'],
            "location": func['location'],
            "doc": func.get('doc', 'No documentation'),
        },
        "callers": {
            "count": len(func['callers']),
            "examples": [
                {
                    "name": functions[cid]['name'],
                    "location": functions[cid]['location'],
                }
                for cid in list(func['callers'])[:3]
                if cid in functions
            ]
        },
        "callees": {
            "count": len(func['callees']),
            "examples": [
                {
                    "name": functions[cid]['name'],
                    "location": functions[cid]['location'],
                }
                for cid in list(func['callees'])[:3]
                if cid in functions
            ]
        }
    }
    
    print(f"\n📋 Context for LLM about '{target_name}':")
    print(f"\n   Function: {context['function_info']['name']}")
    print(f"   Signature: {context['function_info']['signature']}")
    print(f"   Package: {context['function_info']['package']}")
    print(f"   Location: {context['function_info']['location']['file']}:{context['function_info']['location']['line']}")
    
    print(f"\n   Functions that call it ({context['callers']['count']} total):")
    for caller in context['callers']['examples']:
        print(f"     • {caller['name']}")
    
    print(f"\n   Functions it calls ({context['callees']['count']} total):")
    for callee in context['callees']['examples']:
        print(f"     • {callee['name']}")


def example_critical_paths():
    """Example 4: Finding critical functions (most called)."""
    print("\n" + "=" * 60)
    print("Example 4: Critical Functions Analysis")
    print("=" * 60)
    
    graph_path = Path("output/code-graph.json")
    if not graph_path.exists():
        print("Graph not found.")
        return
    
    graph_data = CodeGraphSerializer.load_graph(graph_path)
    functions = graph_data['functions']
    
    # Find most-called functions
    most_called = sorted(
        functions.values(),
        key=lambda f: len(f['callers']),
        reverse=True
    )[:10]
    
    print(f"\n🔥 Top 10 most-called functions:")
    for i, func in enumerate(most_called, 1):
        print(f"   {i:2}. {func['name']:30} - {len(func['callers']):3} callers")
        print(f"       Location: {func['location']['file']}:{func['location']['line']}")


def example_impact_analysis():
    """Example 5: Impact analysis - what happens if we change a function?"""
    print("\n" + "=" * 60)
    print("Example 5: Impact Analysis")
    print("=" * 60)
    
    graph_path = Path("output/code-graph.json")
    if not graph_path.exists():
        print("Graph not found.")
        return
    
    graph_data = CodeGraphSerializer.load_graph(graph_path)
    functions = graph_data['functions']
    
    # Select a function to analyze (pick the first one for demo)
    if not functions:
        print("No functions in graph.")
        return
    
    func_name = list(functions.values())[0]['name']
    func_id = list(functions.keys())[0]
    func = functions[func_id]
    
    print(f"\n📊 Impact analysis for: {func_name}")
    print(f"   If we modify '{func_name}', these functions could be affected:")
    
    def collect_downstream(func_id, depth=0, max_depth=3, visited=None):
        if visited is None:
            visited = set()
        if func_id in visited or depth > max_depth:
            return []
        
        visited.add(func_id)
        affected = []
        
        if func_id in functions:
            for callee_id in functions[func_id]['callees']:
                if callee_id in functions:
                    affected.append((callee_id, depth + 1))
                    affected.extend(collect_downstream(callee_id, depth + 1, max_depth, visited))
        
        return affected
    
    downstream = collect_downstream(func_id)
    downstream = sorted(set((fid, depth) for fid, depth in downstream), key=lambda x: x[1])
    
    for i, (affected_id, depth) in enumerate(downstream[:15]):
        affected_func = functions.get(affected_id)
        if affected_func:
            indent = "  " * (depth + 1)
            print(f"{indent}• {affected_func['name']} (depth {depth})")


if __name__ == "__main__":
    examples = [
        ("Basic Usage", example_basic_usage),
        ("Query Interface", example_query_interface),
        ("Chatbot Context", example_chatbot_context),
        ("Critical Paths", example_critical_paths),
        ("Impact Analysis", example_impact_analysis),
    ]
    
    print("\n" + "=" * 60)
    print("Code Graph - Programmatic Usage Examples")
    print("=" * 60)
    print("\nAvailable examples:")
    
    for i, (name, func) in enumerate(examples, 1):
        print(f"  {i}. {name}")
    
    print("\nRunning all examples...\n")
    
    for name, func in examples:
        try:
            func()
        except Exception as e:
            print(f"\n❌ Error in {name}: {e}")
    
    print("\n" + "=" * 60)
    print("Examples Complete!")
    print("=" * 60)
