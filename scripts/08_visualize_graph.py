#!/usr/bin/env python3
"""
Browsable graph visualization for story_graph.

Generates a self-contained interactive HTML file (vis.js, loaded from CDN)
from the tracked graph_snapshot/ JSONL files. Nodes are colored by type,
edges by relationship type. Node labels are searchable; clicking a node
shows its metadata and connected edges in a side panel.

USAGE:
    python scripts/08_visualize_graph.py
    python scripts/08_visualize_graph.py --output graph.html --limit 500
    python scripts/08_visualize_graph.py --filter "Father Yod,Yogi Bhajan,Richard Moon"

Then open the generated HTML file in a browser, or serve it:
    python -m http.server 0.0.0.0:8080 --directory .
    # visit http://127.0.0.1:8080/graph.html
"""

import argparse
import json
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

NODE_COLORS = {
    "Person": "#e74c3c",
    "Group": "#3498db",
    "Place": "#2ecc71",
    "Event": "#f39c12",
    "Work": "#9b59b6",
    "Claim": "#95a5a6",
}

EDGE_COLORS = {
    "FOUNDED": "#e74c3c",
    "WORKED_AT": "#3498db",
    "MEMBER_OF": "#1abc9c",
    "MENTIONS": "#95a5a6",
    "ABOUT": "#bdc3c7",
    "DESCRIBES": "#f39c12",
    "CONTAINS": "#3498db",
    "ASSERTED_BY": "#e67e22",
    "SUPPORTED_BY": "#2ecc71",
    "CONTRADICTS": "#e74c3c",
    "CREATED": "#9b59b6",
    "LIVED_AT": "#1abc9c",
    "LOCATED_IN": "#2ecc71",
}


def load_snapshot(snapshot_dir: Path) -> tuple[list, list, list]:
    nodes = [json.loads(l) for l in open(snapshot_dir / "nodes.jsonl") if l.strip()]
    edges = [json.loads(l) for l in open(snapshot_dir / "edges.jsonl") if l.strip()]
    sources = [json.loads(l) for l in open(snapshot_dir / "sources.jsonl") if l.strip()]
    return nodes, edges, sources


def build_html(nodes: list, edges: list, sources: list, output: Path) -> Path:
    # Build node/edge data for vis.js
    vis_nodes = []
    for n in nodes:
        ntype = n.get("type", "Claim")
        label = n.get("label", n["id"])[:50]
        vis_nodes.append({
            "id": n["id"],
            "label": label,
            "group": ntype,
            "title": json.dumps({
                "id": n["id"],
                "type": ntype,
                "label": n.get("label", ""),
                "metadata": n.get("metadata", {}),
                "source_urls": n.get("source_urls", []),
            }, default=str),
            "color": {"background": NODE_COLORS.get(ntype, "#bdc3c7"),
                      "border": "#34495e"},
            "font": {"size": 10},
        })

    vis_edges = []
    for e in edges:
        vis_edges.append({
            "from": e["src_id"],
            "to": e["dst_id"],
            "label": e.get("rel_type", ""),
            "color": {"color": EDGE_COLORS.get(e.get("rel_type"), "#bdc3c7"),
                      "opacity": 0.6},
            "arrows": "to",
            "font": {"size": 8, "align": "middle"},
        })

    sources_map = {s["id"]: s for s in sources}

    html = f"""<!DOCTYPE html>
<html>
<head>
<title>Story Graph — {len(nodes)} nodes / {len(edges)} edges</title>
<script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
<style>
body {{ font-family: sans-serif; margin: 0; padding: 0; }}
#network {{ width: 70%; height: 100vh; float: left; }}
#sidebar {{ width: 30%; height: 100vh; float: right; overflow-y: auto;
            padding: 15px; box-sizing: border-box; background: #f8f9fa;
            border-left: 1px solid #ddd; }}
#search {{ width: 100%; padding: 8px; margin-bottom: 10px; font-size: 14px; }}
.legend {{ display: inline-block; width: 12px; height: 12px; margin-right: 4px; }}
h3 {{ margin-top: 0; }}
.node-detail {{ font-size: 13px; word-wrap: break-word; }}
.node-detail pre {{ white-space: pre-wrap; font-size: 11px; background: #fff;
                    padding: 8px; border-radius: 4px; border: 1px solid #eee; }}
.edge-list {{ font-size: 12px; }}
.edge-list li {{ margin-bottom: 4px; }}
</style>
</head>
<body>
<div id="network"></div>
<div id="sidebar">
  <h3>Story Graph Browser</h3>
  <p>{len(nodes)} nodes, {len(edges)} edges, {len(sources)} sources</p>
  <input id="search" type="text" placeholder="Search node labels..." oninput="filterNodes()">
  <div>
    <b>Legend:</b><br>
    <span class="legend" style="background:#e74c3c"></span>Person
    <span class="legend" style="background:#3498db"></span>Group
    <span class="legend" style="background:#2ecc71"></span>Place
    <span class="legend" style="background:#f39c12"></span>Event
    <span class="legend" style="background:#9b59b6"></span>Work
    <span class="legend" style="background:#95a5a6"></span>Claim
  </div>
  <hr>
  <div id="detail" class="node-detail"><p>Click a node to see details.</p></div>
</div>
<script>
var nodes = new vis.DataSet({json.dumps(vis_nodes)});
var edges = new vis.DataSet({json.dumps(vis_edges)});
var container = document.getElementById('network');
var data = {{ nodes: nodes, edges: edges }};
var options = {{
  nodes: {{ shape: 'dot', size: 16 }},
  edges: {{ width: 0.5, smooth: {{ type: 'continuous' }} }},
  physics: {{
    barnesHut: {{ gravitationalConstant: -3000, springLength: 120 }},
    stabilization: {{ iterations: 150 }}
  }},
  interaction: {{ hover: true, tooltipDelay: 200 }}
}};
var network = new vis.Network(container, data, options);

var sourcesMap = {json.dumps(sources_map)};

network.on('click', function(params) {{
  if (params.nodes.length > 0) {{
    var nodeId = params.nodes[0];
    var node = nodes.get(nodeId);
    var detail = document.getElementById('detail');
    var info = JSON.parse(node.title);
    var html = '<h4>' + info.label + '</h4>';
    html += '<p><b>ID:</b> ' + info.id + '<br>';
    html += '<b>Type:</b> ' + info.type + '</p>';
    if (info.metadata && Object.keys(info.metadata).length > 0) {{
      html += '<pre>' + JSON.stringify(info.metadata, null, 2) + '</pre>';
    }}
    if (info.source_urls && info.source_urls.length > 0) {{
      html += '<p><b>Source URLs:</b><br>';
      info.source_urls.forEach(function(u) {{
        html += '<a href="' + u + '" target="_blank">' + u + '</a><br>';
      }});
      html += '</p>';
    }}
    // Connected edges
    var connected = edges.get().filter(function(e) {{
      return e.from === nodeId || e.to === nodeId;
    }});
    html += '<p><b>Connections (' + connected.length + '):</b></p>';
    html += '<ul class="edge-list">';
    connected.slice(0, 50).forEach(function(e) {{
      var other = e.from === nodeId ? e.to : e.from;
      var otherNode = nodes.get(other);
      var otherLabel = otherNode ? otherNode.label : other;
      html += '<li>' + e.label + ' → ' + otherLabel + '</li>';
    }});
    if (connected.length > 50) html += '<li>... ' + (connected.length - 50) + ' more</li>';
    html += '</ul>';
    detail.innerHTML = html;
  }}
}});

function filterNodes() {{
  var q = document.getElementById('search').value.toLowerCase();
  var all = nodes.get();
  var matches = all.filter(function(n) {{
    return n.label.toLowerCase().indexOf(q) >= 0;
  }});
  if (q.length === 0) {{
    network.setData(data);
  }} else {{
    var matchIds = new Set(matches.map(function(n) {{ return n.id; }}));
    // Also include directly connected nodes
    var connectedIds = new Set(matchIds);
    edges.get().forEach(function(e) {{
      if (matchIds.has(e.from)) connectedIds.add(e.to);
      if (matchIds.has(e.to)) connectedIds.add(e.from);
    }});
    var filteredNodes = all.filter(function(n) {{ return connectedIds.has(n.id); }});
    var filteredEdges = edges.get().filter(function(e) {{
      return connectedIds.has(e.from) && connectedIds.has(e.to);
    }});
    network.setData({{ nodes: new vis.DataSet(filteredNodes), edges: new vis.DataSet(filteredEdges) }});
  }}
}}
</script>
</body>
</html>
"""
    output.write_text(html)
    return output


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Browsable graph visualization for story_graph")
    p.add_argument("--output", type=Path, default=Path("graph.html"),
                   help="Output HTML file (default: graph.html)")
    p.add_argument("--snapshot", type=Path, default=Path("graph_snapshot"),
                   help="Snapshot directory (default: graph_snapshot)")
    p.add_argument("--limit", type=int, default=None,
                   help="Limit number of nodes (for performance)")
    p.add_argument("--filter", type=str, default=None,
                   help="Comma-separated node labels to include (with neighbors)")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    nodes, edges, sources = load_snapshot(args.snapshot)
    print(f"Loaded {len(nodes)} nodes, {len(edges)} edges, {len(sources)} sources")

    if args.filter:
        terms = [t.strip().lower() for t in args.filter.split(",")]
        keep = set()
        for n in nodes:
            if any(t in n.get("label", "").lower() for t in terms):
                keep.add(n["id"])
        # Add 1-hop neighbors
        for e in edges:
            if e["src_id"] in keep:
                keep.add(e["dst_id"])
            if e["dst_id"] in keep:
                keep.add(e["src_id"])
        nodes = [n for n in nodes if n["id"] in keep]
        edges = [e for e in edges if e["src_id"] in keep and e["dst_id"] in keep]
        print(f"Filtered to {len(nodes)} nodes, {len(edges)} edges")

    if args.limit and len(nodes) > args.limit:
        # Keep highest-degree nodes
        from collections import Counter
        degree = Counter()
        for e in edges:
            degree[e["src_id"]] += 1
            degree[e["dst_id"]] += 1
        top = set(n for n, _ in degree.most_common(args.limit))
        nodes = [n for n in nodes if n["id"] in top]
        edges = [e for e in edges if e["src_id"] in top and e["dst_id"] in top]
        print(f"Limited to {len(nodes)} highest-degree nodes")

    out = build_html(nodes, edges, sources, args.output)
    print(f"\n✓ Generated {out} ({out.stat().st_size // 1024} KB)")
    print(f"  Open: file://{out.resolve()}")
    print(f"  Or serve: python -m http.server 0.0.0.0:8080 --directory {out.parent}")
    print(f"  Then visit: http://127.0.0.1:8080/{out.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
