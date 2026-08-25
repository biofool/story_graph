#!/usr/bin/env python3
"""
Graph enrichment API server for story_graph.

A lightweight Flask server that serves the browsable graph visualization
and exposes REST endpoints for interactively adding nodes, edges, claims,
and sources. All mutations go through GraphDB's upsert path and can be
persisted to the tracked graph_snapshot/ via the /api/export endpoint.

USAGE:
    python scripts/09_graph_api.py
    python scripts/09_graph_api.py --port 8090 --db data/graph.db

Then open http://127.0.0.1:8090 in a browser.
"""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from flask import Flask, jsonify, request, send_file

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.storage.graph_db import GraphDB
from src.storage.json_export import export_to_json, import_from_json
from src.storage.models import (
    BiasHint,
    ClaimSourceLink,
    GraphEdge,
    GraphNode,
    NodeType,
    RelationType,
    SourceClass,
    SourceRecord,
)

app = Flask(__name__, static_folder=None)

# Global DB handle — opened in main(), reused across requests.
# Flask's dev server is single-threaded by default so this is safe.
_DB: GraphDB | None = None
_SNAPSHOT_DIR: Path = Path("graph_snapshot")
_NODE_COLORS = {
    "Person": "#e74c3c", "Group": "#3498db", "Place": "#2ecc71",
    "Event": "#f39c12", "Work": "#9b59b6", "Claim": "#95a5a6",
}
_EDGE_COLORS = {
    "FOUNDED": "#e74c3c", "WORKED_AT": "#3498db", "MEMBER_OF": "#1abc9c",
    "MENTIONS": "#95a5a6", "ABOUT": "#bdc3c7", "DESCRIBES": "#f39c12",
    "CONTAINS": "#3498db", "ASSERTED_BY": "#e67e22", "SUPPORTED_BY": "#2ecc71",
    "CONTRADICTS": "#e74c3c", "CREATED": "#9b59b6", "LIVED_AT": "#1abc9c",
    "LOCATED_IN": "#2ecc71",
}


def get_db() -> GraphDB:
    global _DB
    if _DB is None or _DB._conn is None:
        raise RuntimeError("DB not initialized")
    return _DB


def _slug(label: str) -> str:
    """Generate a URL-safe slug from a label."""
    s = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")
    return s or "unnamed"


def _gen_node_id(node_type: str, label: str) -> str:
    """Generate a node ID from type + label slug."""
    prefix = node_type.lower()
    slug = _slug(label)
    base = f"{prefix}:{slug}"
    # Check for collisions
    db = get_db()
    if db.get_node(base) is None:
        return base
    # Append short hash if collision
    h = hashlib.sha256(label.encode()).hexdigest()[:8]
    return f"{base}-{h}"


# --- Routes ---

@app.route("/")
def index():
    """Serve the visualization HTML, regenerated live from the DB."""
    html = _build_viz_html()
    from io import BytesIO
    return send_file(BytesIO(html.encode("utf-8")),
                     mimetype="text/html",
                     download_name="index.html")


@app.route("/api/graph")
def api_graph():
    """Return all nodes, edges, sources as JSON for vis.js."""
    db = get_db()
    nodes = []
    for n in db.get_all_nodes():
        ntype = n.type.value
        nodes.append({
            "id": n.id,
            "label": n.label[:50],
            "group": ntype,
            "title": json.dumps({
                "id": n.id, "type": ntype, "label": n.label,
                "metadata": n.metadata, "source_urls": n.source_urls,
            }, default=str),
            "color": {"background": _NODE_COLORS.get(ntype, "#bdc3c7"),
                      "border": "#34495e"},
            "font": {"size": 10},
        })
    edges = []
    for e in db.get_all_edges():
        edges.append({
            "from": e.src_id, "to": e.dst_id, "label": e.rel_type.value,
            "color": {"color": _EDGE_COLORS.get(e.rel_type.value, "#bdc3c7"),
                      "opacity": 0.6},
            "arrows": "to", "font": {"size": 8, "align": "middle"},
        })
    sources = []
    for s in db.get_all_sources():
        sources.append({
            "id": s.id, "url": s.url, "title": s.title, "author": s.author,
            "platform": s.platform, "source_class": s.source_class.value if s.source_class else None,
            "bias_hint": s.bias_hint.value if s.bias_hint else None,
        })
    return jsonify({"nodes": nodes, "edges": edges, "sources": sources,
                    "counts": {"nodes": len(nodes), "edges": len(edges),
                               "sources": len(sources)}})


@app.route("/api/nodes", methods=["POST"])
def api_add_node():
    """Add a node. Required: type, label. Optional: id, canonical_name, metadata, source_urls."""
    data = request.get_json(force=True)
    try:
        node_type = NodeType(data["type"])
    except (KeyError, ValueError):
        return jsonify({"error": f"Invalid or missing type. Valid: {[t.value for t in NodeType]}"}), 400
    label = data.get("label", "").strip()
    if not label:
        return jsonify({"error": "label is required"}), 400
    node_id = data.get("id") or _gen_node_id(node_type.value, label)
    node = GraphNode(
        id=node_id, type=node_type, label=label,
        canonical_name=data.get("canonical_name", label.lower()),
        metadata=data.get("metadata", {}),
        source_urls=data.get("source_urls", []),
    )
    db = get_db()
    db.add_node(node)
    return jsonify({"ok": True, "id": node_id, "node": {
        "id": node_id, "type": node_type.value, "label": label,
        "canonical_name": node.canonical_name, "metadata": node.metadata,
        "source_urls": node.source_urls,
    }})


@app.route("/api/edges", methods=["POST"])
def api_add_edge():
    """Add an edge. Required: src_id, rel_type, dst_id. Optional: metadata."""
    data = request.get_json(force=True)
    try:
        rel_type = RelationType(data["rel_type"])
    except (KeyError, ValueError):
        return jsonify({"error": f"Invalid or missing rel_type. Valid: {[r.value for r in RelationType]}"}), 400
    src_id = data.get("src_id", "").strip()
    dst_id = data.get("dst_id", "").strip()
    if not src_id or not dst_id:
        return jsonify({"error": "src_id and dst_id are required"}), 400
    db = get_db()
    if db.get_node(src_id) is None:
        return jsonify({"error": f"src_id '{src_id}' not found"}), 404
    if db.get_node(dst_id) is None:
        return jsonify({"error": f"dst_id '{dst_id}' not found"}), 404
    edge = GraphEdge(src_id=src_id, rel_type=rel_type, dst_id=dst_id,
                     metadata=data.get("metadata", {}))
    db.add_edge(edge)
    return jsonify({"ok": True, "edge": {
        "src_id": src_id, "rel_type": rel_type.value, "dst_id": dst_id,
    }})


@app.route("/api/sources", methods=["POST"])
def api_add_source():
    """Add a source. Required: url. Optional: id, title, author, publish_date, platform, source_class, bias_hint."""
    data = request.get_json(force=True)
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "url is required"}), 400
    src_id = data.get("id") or f"source:{_slug(url)}"
    # Parse enums
    source_class = None
    if data.get("source_class"):
        try:
            source_class = SourceClass(data["source_class"])
        except ValueError:
            return jsonify({"error": f"Invalid source_class. Valid: {[s.value for s in SourceClass]}"}), 400
    bias_hint = None
    if data.get("bias_hint"):
        try:
            bias_hint = BiasHint(data["bias_hint"])
        except ValueError:
            return jsonify({"error": f"Invalid bias_hint. Valid: {[b.value for b in BiasHint]}"}), 400
    source = SourceRecord(
        id=src_id, url=url, title=data.get("title"),
        author=data.get("author"), publish_date=data.get("publish_date"),
        platform=data.get("platform"), source_class=source_class,
        bias_hint=bias_hint,
    )
    db = get_db()
    db.add_source(source)
    return jsonify({"ok": True, "id": src_id, "source": {
        "id": src_id, "url": url, "title": source.title,
        "platform": source.platform,
    }})


@app.route("/api/claims", methods=["POST"])
def api_add_claim():
    """Add a claim with optional source and auto-created ABOUT + ASSERTED_BY edges.

    Required: claim_text, about_id (target node ID)
    Optional: stance, claim_type, confidence, source_id (existing source),
              source_url (creates a new source if source_id not given),
              asserted_by_id (defaults to source author or 'unknown'),
              claim_id (auto-generated if not provided)
    """
    data = request.get_json(force=True)
    claim_text = data.get("claim_text", "").strip()
    if not claim_text:
        return jsonify({"error": "claim_text is required"}), 400
    about_id = data.get("about_id", "").strip()
    if not about_id:
        return jsonify({"error": "about_id is required (target node for ABOUT edge)"}), 400
    db = get_db()
    if db.get_node(about_id) is None:
        return jsonify({"error": f"about_id '{about_id}' not found"}), 404

    # Generate claim ID
    h = hashlib.sha256(claim_text.encode()).hexdigest()[:16]
    claim_id = data.get("claim_id") or f"claim:ui:{h}"

    # Parse stance / claim_type (stored as strings in metadata, not enums)
    stance = data.get("stance", "neutral")
    claim_type = data.get("claim_type", "biographical")
    confidence = float(data.get("confidence", 0.5))

    # Create the claim node
    claim_node = GraphNode(
        id=claim_id, type=NodeType.CLAIM, label=claim_text[:100],
        metadata={
            "claim_text": claim_text, "stance": stance,
            "claim_type": claim_type, "confidence": confidence,
            "source": data.get("source_note", "Added via web UI"),
        },
        source_urls=[],
    )
    db.add_node(claim_node)

    # ABOUT edge
    db.add_edge(GraphEdge(src_id=claim_id, rel_type=RelationType.ABOUT,
                          dst_id=about_id, metadata={}))

    # Source handling
    source_id = data.get("source_id")
    source_url = data.get("source_url", "").strip()
    if not source_id and source_url:
        # Create a new source
        source_id = f"source:{_slug(source_url)}"
        source_class = None
        if data.get("source_class"):
            try:
                source_class = SourceClass(data["source_class"])
            except ValueError:
                pass
        bias_hint = None
        if data.get("bias_hint"):
            try:
                bias_hint = BiasHint(data["bias_hint"])
            except ValueError:
                pass
        source = SourceRecord(
            id=source_id, url=source_url, title=data.get("source_title"),
            author=data.get("source_author"),
            platform=data.get("source_platform", "web"),
            source_class=source_class, bias_hint=bias_hint,
        )
        db.add_source(source)

    if source_id:
        # Claim-source link
        db.add_claim_source_link(ClaimSourceLink(
            claim_id=claim_id, source_id=source_id,
        ))

    # ASSERTED_BY edge — link to a person, or create one
    asserted_by_id = data.get("asserted_by_id", "").strip()
    if asserted_by_id:
        if db.get_node(asserted_by_id) is None:
            return jsonify({"error": f"asserted_by_id '{asserted_by_id}' not found"}), 404
        db.add_edge(GraphEdge(src_id=claim_id, rel_type=RelationType.ASSERTED_BY,
                              dst_id=asserted_by_id, metadata={}))

    return jsonify({"ok": True, "claim_id": claim_id, "about_id": about_id,
                    "source_id": source_id, "asserted_by_id": asserted_by_id or None})


@app.route("/api/export", methods=["POST"])
def api_export():
    """Persist the in-memory DB to graph_snapshot/ JSONL files."""
    db = get_db()
    counts = export_to_json(db, _SNAPSHOT_DIR)
    return jsonify({"ok": True, "counts": counts})


@app.route("/api/node/<path:node_id>")
def api_node_detail(node_id: str):
    """Get full details for a single node, including connected edges."""
    db = get_db()
    node = db.get_node(node_id)
    if node is None:
        return jsonify({"error": "not found"}), 404
    edges_out = []
    for e in db.get_edges_from(node_id):
        dst = db.get_node(e.dst_id)
        edges_out.append({"rel_type": e.rel_type.value, "dst_id": e.dst_id,
                          "dst_label": dst.label if dst else "?",
                          "dst_type": dst.type.value if dst else "?",
                          "direction": "out"})
    for e in db.get_edges_to(node_id):
        src = db.get_node(e.src_id)
        edges_out.append({"rel_type": e.rel_type.value, "src_id": e.src_id,
                          "src_label": src.label if src else "?",
                          "src_type": src.type.value if src else "?",
                          "direction": "in"})
    # Claims about this node
    claims = db.get_claims_about(node_id)
    return jsonify({
        "node": {
            "id": node.id, "type": node.type.value, "label": node.label,
            "canonical_name": node.canonical_name, "metadata": node.metadata,
            "source_urls": node.source_urls,
        },
        "edges": edges_out,
        "claims": [{"id": c.id, "label": c.label,
                     "metadata": c.metadata} for c in claims],
    })


# --- Visualization HTML ---

def _build_viz_html() -> str:
    """Build the interactive visualization HTML with enrichment forms."""
    db = get_db()
    n_nodes = db.get_node_count()
    n_edges = db.get_edge_count()
    n_sources = db.get_source_count()

    # Get all node IDs for the edge form dropdowns
    all_nodes = db.get_all_nodes()
    node_options = json.dumps([{"id": n.id, "label": n.label[:60], "type": n.type.value}
                               for n in all_nodes])
    all_sources = db.get_all_sources()
    source_options = json.dumps([{"id": s.id, "title": s.title or s.url[:60]}
                                 for s in all_sources])

    node_types = [t.value for t in NodeType]
    rel_types = [r.value for r in RelationType]
    source_classes = [s.value for s in SourceClass]
    bias_hints = [b.value for b in BiasHint]

    return f"""<!DOCTYPE html>
<html>
<head>
<title>Story Graph — {n_nodes} nodes / {n_edges} edges</title>
<script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
<style>
body {{ font-family: sans-serif; margin: 0; padding: 0; }}
#network {{ width: 65%; height: 100vh; float: left; }}
#sidebar {{ width: 35%; height: 100vh; float: right; overflow-y: auto;
            padding: 12px; box-sizing: border-box; background: #f8f9fa;
            border-left: 1px solid #ddd; }}
#search {{ width: 100%; padding: 6px; margin-bottom: 8px; font-size: 13px; }}
.legend {{ display: inline-block; width: 10px; height: 10px; margin-right: 3px; }}
h3 {{ margin-top: 0; font-size: 16px; }}
h4 {{ margin: 8px 0 4px 0; font-size: 14px; }}
.node-detail {{ font-size: 12px; word-wrap: break-word; }}
.node-detail pre {{ white-space: pre-wrap; font-size: 11px; background: #fff;
                    padding: 6px; border-radius: 3px; border: 1px solid #eee; }}
.edge-list {{ font-size: 11px; }}
.edge-list li {{ margin-bottom: 2px; }}
.tab-bar {{ display: flex; gap: 4px; margin-bottom: 8px; }}
.tab {{ padding: 4px 10px; background: #ddd; border-radius: 4px 4px 0 0;
        cursor: pointer; font-size: 12px; }}
.tab.active {{ background: #3498db; color: white; }}
.tab-content {{ display: none; }}
.tab-content.active {{ display: block; }}
.form-group {{ margin-bottom: 6px; }}
.form-group label {{ display: block; font-size: 11px; font-weight: bold; margin-bottom: 2px; }}
.form-group input, .form-group select, .form-group textarea {{
  width: 100%; padding: 4px; font-size: 12px; box-sizing: border-box;
  border: 1px solid #ccc; border-radius: 3px;
}}
.form-group textarea {{ height: 50px; }}
.btn {{ padding: 6px 14px; background: #2ecc71; color: white; border: none;
        border-radius: 4px; cursor: pointer; font-size: 13px; }}
.btn:hover {{ background: #27ae60; }}
.btn-export {{ background: #f39c12; }}
.btn-export:hover {{ background: #e67e22; }}
.status {{ font-size: 11px; padding: 4px; margin: 4px 0; border-radius: 3px; }}
.status.ok {{ background: #d4edda; color: #155724; }}
.status.err {{ background: #f8d7da; color: #721c24; }}
</style>
</head>
<body>
<div id="network"></div>
<div id="sidebar">
  <h3>Story Graph Browser + Enrichment</h3>
  <p id="counts">{n_nodes} nodes, {n_edges} edges, {n_sources} sources</p>
  <input id="search" type="text" placeholder="Search node labels..." oninput="filterNodes()">
  <div style="font-size:11px;margin-bottom:8px">
    <span class="legend" style="background:#e74c3c"></span>Person
    <span class="legend" style="background:#3498db"></span>Group
    <span class="legend" style="background:#2ecc71"></span>Place
    <span class="legend" style="background:#f39c12"></span>Event
    <span class="legend" style="background:#9b59b6"></span>Work
    <span class="legend" style="background:#95a5a6"></span>Claim
  </div>

  <div class="tab-bar">
    <div class="tab active" onclick="showTab('detail')">Detail</div>
    <div class="tab" onclick="showTab('addnode')">Add Node</div>
    <div class="tab" onclick="showTab('addedge')">Add Edge</div>
    <div class="tab" onclick="showTab('addclaim')">Add Claim</div>
    <div class="tab" onclick="showTab('addsource')">Add Source</div>
  </div>

  <!-- Detail tab -->
  <div id="tab-detail" class="tab-content active">
    <div id="detail" class="node-detail"><p>Click a node to see details.</p></div>
  </div>

  <!-- Add Node tab -->
  <div id="tab-addnode" class="tab-content">
    <h4>Add New Node</h4>
    <div class="form-group"><label>Type</label>
      <select id="node-type">{"".join(f'<option value="{t}">{t}</option>' for t in node_types)}</select>
    </div>
    <div class="form-group"><label>Label *</label>
      <input id="node-label" type="text" placeholder="e.g. John Smith">
    </div>
    <div class="form-group"><label>Metadata (JSON, optional)</label>
      <textarea id="node-meta" placeholder='{{"note": "some note"}}'></textarea>
    </div>
    <div class="form-group"><label>Source URLs (comma-separated, optional)</label>
      <input id="node-urls" type="text" placeholder="https://example.com">
    </div>
    <button class="btn" onclick="addNode()">Add Node</button>
    <div id="node-status"></div>
  </div>

  <!-- Add Edge tab -->
  <div id="tab-addedge" class="tab-content">
    <h4>Add New Edge</h4>
    <div class="form-group"><label>Source Node *</label>
      <select id="edge-src"></select>
    </div>
    <div class="form-group"><label>Relationship *</label>
      <select id="edge-rel">{"".join(f'<option value="{r}">{r}</option>' for r in rel_types)}</select>
    </div>
    <div class="form-group"><label>Target Node *</label>
      <select id="edge-dst"></select>
    </div>
    <div class="form-group"><label>Metadata (JSON, optional)</label>
      <textarea id="edge-meta" placeholder='{{}}'></textarea>
    </div>
    <button class="btn" onclick="addEdge()">Add Edge</button>
    <div id="edge-status"></div>
  </div>

  <!-- Add Claim tab -->
  <div id="tab-addclaim" class="tab-content">
    <h4>Add New Claim</h4>
    <div class="form-group"><label>Claim Text *</label>
      <textarea id="claim-text" placeholder="The claim being made..." style="height:60px"></textarea>
    </div>
    <div class="form-group"><label>About (target node) *</label>
      <select id="claim-about"></select>
    </div>
    <div class="form-group"><label>Stance</label>
      <select id="claim-stance">
        <option value="neutral">neutral</option>
        <option value="supportive">supportive</option>
        <option value="critical">critical</option>
        <option value="self-mythologizing">self-mythologizing</option>
      </select>
    </div>
    <div class="form-group"><label>Claim Type</label>
      <select id="claim-type">
        <option value="biographical">biographical</option>
        <option value="abuse_allegation">abuse_allegation</option>
        <option value="financial_control">financial_control</option>
        <option value="sexual_control">sexual_control</option>
        <option value="documentary_critique">documentary_critique</option>
        <option value="historical_dispute">historical_dispute</option>
      </select>
    </div>
    <div class="form-group"><label>Confidence (0.0–1.0)</label>
      <input id="claim-conf" type="number" min="0" max="1" step="0.05" value="0.5">
    </div>
    <div class="form-group"><label>Asserted By (person, optional)</label>
      <select id="claim-asserted"><option value="">— none —</option></select>
    </div>
    <div class="form-group"><label>Source URL (optional, creates source if new)</label>
      <input id="claim-source-url" type="text" placeholder="https://...">
    </div>
    <div class="form-group"><label>Source Title (optional)</label>
      <input id="claim-source-title" type="text">
    </div>
    <div class="form-group"><label>Source Author (optional)</label>
      <input id="claim-source-author" type="text">
    </div>
    <div class="form-group"><label>Source Class</label>
      <select id="claim-source-class">
        <option value="">— auto —</option>
        {"".join(f'<option value="{s}">{s}</option>' for s in source_classes)}
      </select>
    </div>
    <div class="form-group"><label>Bias Hint</label>
      <select id="claim-bias">
        <option value="">— auto —</option>
        {"".join(f'<option value="{b}">{b}</option>' for b in bias_hints)}
      </select>
    </div>
    <button class="btn" onclick="addClaim()">Add Claim</button>
    <div id="claim-status"></div>
  </div>

  <!-- Add Source tab -->
  <div id="tab-addsource" class="tab-content">
    <h4>Add New Source</h4>
    <div class="form-group"><label>URL *</label>
      <input id="src-url" type="text" placeholder="https://...">
    </div>
    <div class="form-group"><label>Title</label>
      <input id="src-title" type="text">
    </div>
    <div class="form-group"><label>Author</label>
      <input id="src-author" type="text">
    </div>
    <div class="form-group"><label>Platform</label>
      <input id="src-platform" type="text" placeholder="e.g. wikipedia.org">
    </div>
    <div class="form-group"><label>Source Class</label>
      <select id="src-class">
        <option value="">— none —</option>
        {"".join(f'<option value="{s}">{s}</option>' for s in source_classes)}
      </select>
    </div>
    <div class="form-group"><label>Bias Hint</label>
      <select id="src-bias">
        <option value="">— none —</option>
        {"".join(f'<option value="{b}">{b}</option>' for b in bias_hints)}
      </select>
    </div>
    <button class="btn" onclick="addSource()">Add Source</button>
    <div id="src-status"></div>
  </div>

  <hr>
  <button class="btn btn-export" onclick="exportSnapshot()">Export to Snapshot</button>
  <div id="export-status"></div>
</div>

<script>
var allNodeOptions = {node_options};
var allSourceOptions = {source_options};

// Populate dropdowns
function populateDropdowns() {{
  var edgeSrc = document.getElementById('edge-src');
  var edgeDst = document.getElementById('edge-dst');
  var claimAbout = document.getElementById('claim-about');
  var claimAsserted = document.getElementById('claim-asserted');
  allNodeOptions.forEach(function(n) {{
    var opt1 = document.createElement('option');
    opt1.value = n.id; opt1.text = '[' + n.type + '] ' + n.label;
    edgeSrc.appendChild(opt1.cloneNode(true));
    edgeDst.appendChild(opt1.cloneNode(true));
    if (n.type === 'Person') {{
      var opt2 = document.createElement('option');
      opt2.value = n.id; opt2.text = n.label;
      claimAsserted.appendChild(opt2);
    }}
    // Only non-Claim nodes as claim targets
    if (n.type !== 'Claim') {{
      var opt3 = document.createElement('option');
      opt3.value = n.id; opt3.text = '[' + n.type + '] ' + n.label;
      claimAbout.appendChild(opt3);
    }}
  }});
}}

// --- Network ---
var nodes, edges, network, data;
function initNetwork() {{
  fetch('/api/graph').then(r => r.json()).then(d => {{
    nodes = new vis.DataSet(d.nodes);
    edges = new vis.DataSet(d.edges);
    data = {{ nodes: nodes, edges: edges }};
    var container = document.getElementById('network');
    var options = {{
      nodes: {{ shape: 'dot', size: 16 }},
      edges: {{ width: 0.5, smooth: {{ type: 'continuous' }} }},
      physics: {{ barnesHut: {{ gravitationalConstant: -3000, springLength: 120 }},
                  stabilization: {{ iterations: 100 }} }},
      interaction: {{ hover: true, tooltipDelay: 200 }}
    }};
    network = new vis.Network(container, data, options);
    document.getElementById('counts').textContent =
      d.counts.nodes + ' nodes, ' + d.counts.edges + ' edges, ' + d.counts.sources + ' sources';
    network.on('click', function(params) {{
      if (params.nodes.length > 0) showNodeDetail(params.nodes[0]);
    }});
  }});
}}

function showNodeDetail(nodeId) {{
  fetch('/api/node/' + encodeURIComponent(nodeId)).then(r => r.json()).then(d => {{
    var n = d.node;
    var html = '<h4>' + n.label + '</h4>';
    html += '<p><b>ID:</b> ' + n.id + '<br><b>Type:</b> ' + n.type + '</p>';
    if (n.metadata && Object.keys(n.metadata).length > 0)
      html += '<pre>' + JSON.stringify(n.metadata, null, 2) + '</pre>';
    if (n.source_urls && n.source_urls.length > 0) {{
      html += '<p><b>Source URLs:</b><br>';
      n.source_urls.forEach(function(u) {{
        html += '<a href="' + u + '" target="_blank">' + u + '</a><br>';
      }});
      html += '</p>';
    }}
    html += '<p><b>Connections (' + d.edges.length + '):</b></p><ul class="edge-list">';
    d.edges.slice(0, 50).forEach(function(e) {{
      if (e.direction === 'out')
        html += '<li>' + e.rel_type + ' → ' + e.dst_label + '</li>';
      else
        html += '<li>' + e.src_label + ' → ' + e.rel_type + '</li>';
    }});
    if (d.edges.length > 50) html += '<li>... ' + (d.edges.length - 50) + ' more</li>';
    html += '</ul>';
    if (d.claims.length > 0) {{
      html += '<p><b>Claims (' + d.claims.length + '):</b></p><ul class="edge-list">';
      d.claims.forEach(function(c) {{
        html += '<li>[' + (c.metadata.stance||'?') + ', conf=' + (c.metadata.confidence||'?') +
                '] ' + c.label.substring(0,80) + '</li>';
      }});
      html += '</ul>';
    }}
    document.getElementById('detail').innerHTML = html;
  }});
}}

function filterNodes() {{
  var q = document.getElementById('search').value.toLowerCase();
  if (q.length === 0) {{ network.setData(data); return; }}
  var all = nodes.get();
  var matches = all.filter(function(n) {{ return n.label.toLowerCase().indexOf(q) >= 0; }});
  var matchIds = new Set(matches.map(function(n) {{ return n.id; }}));
  var connectedIds = new Set(matchIds);
  edges.get().forEach(function(e) {{
    if (matchIds.has(e.from)) connectedIds.add(e.to);
    if (matchIds.has(e.to)) connectedIds.add(e.from);
  }});
  var fn = all.filter(function(n) {{ return connectedIds.has(n.id); }});
  var fe = edges.get().filter(function(e) {{
    return connectedIds.has(e.from) && connectedIds.has(e.to);
  }});
  network.setData({{ nodes: new vis.DataSet(fn), edges: new vis.DataSet(fe) }});
}}

// --- Tabs ---
function showTab(name) {{
  document.querySelectorAll('.tab').forEach(function(t) {{ t.classList.remove('active'); }});
  document.querySelectorAll('.tab-content').forEach(function(c) {{ c.classList.remove('active'); }});
  event.target.classList.add('active');
  document.getElementById('tab-' + name).classList.add('active');
}}

// --- Enrichment API calls ---
function showStatus(id, msg, ok) {{
  var el = document.getElementById(id);
  el.innerHTML = '<div class="status ' + (ok ? 'ok' : 'err') + '">' + msg + '</div>';
  setTimeout(function() {{ el.innerHTML = ''; }}, 5000);
}}

function refreshGraph() {{
  fetch('/api/graph').then(r => r.json()).then(d => {{
    nodes = new vis.DataSet(d.nodes);
    edges = new vis.DataSet(d.edges);
    data = {{ nodes: nodes, edges: edges }};
    network.setData(data);
    document.getElementById('counts').textContent =
      d.counts.nodes + ' nodes, ' + d.counts.edges + ' edges, ' + d.counts.sources + ' sources';
    // Refresh dropdowns
    allNodeOptions = d.nodes.map(function(n) {{
      return {{ id: n.id, label: n.label, type: n.group }};
    }});
    document.getElementById('edge-src').innerHTML = '';
    document.getElementById('edge-dst').innerHTML = '';
    document.getElementById('claim-about').innerHTML = '';
    document.getElementById('claim-asserted').innerHTML = '<option value="">— none —</option>';
    populateDropdowns();
  }});
}}

function addNode() {{
  var meta = document.getElementById('node-meta').value.trim();
  var body = {{
    type: document.getElementById('node-type').value,
    label: document.getElementById('node-label').value.trim(),
    source_urls: document.getElementById('node-urls').value.split(',').map(s=>s.trim()).filter(Boolean),
  }};
  if (meta) {{ try {{ body.metadata = JSON.parse(meta); }} catch(e) {{
    showStatus('node-status', 'Invalid JSON metadata', false); return; }} }}
  fetch('/api/nodes', {{method:'POST', headers:{{'Content-Type':'application/json'}}, body: JSON.stringify(body)}})
    .then(r => r.json()).then(d => {{
      if (d.error) {{ showStatus('node-status', d.error, false); return; }}
      showStatus('node-status', 'Added: ' + d.id, true);
      document.getElementById('node-label').value = '';
      document.getElementById('node-meta').value = '';
      document.getElementById('node-urls').value = '';
      refreshGraph();
    }});
}}

function addEdge() {{
  var meta = document.getElementById('edge-meta').value.trim();
  var body = {{
    src_id: document.getElementById('edge-src').value,
    rel_type: document.getElementById('edge-rel').value,
    dst_id: document.getElementById('edge-dst').value,
  }};
  if (meta) {{ try {{ body.metadata = JSON.parse(meta); }} catch(e) {{
    showStatus('edge-status', 'Invalid JSON metadata', false); return; }} }}
  fetch('/api/edges', {{method:'POST', headers:{{'Content-Type':'application/json'}}, body: JSON.stringify(body)}})
    .then(r => r.json()).then(d => {{
      if (d.error) {{ showStatus('edge-status', d.error, false); return; }}
      showStatus('edge-status', 'Added edge: ' + body.rel_type, true);
      refreshGraph();
    }});
}}

function addClaim() {{
  var body = {{
    claim_text: document.getElementById('claim-text').value.trim(),
    about_id: document.getElementById('claim-about').value,
    stance: document.getElementById('claim-stance').value,
    claim_type: document.getElementById('claim-type').value,
    confidence: parseFloat(document.getElementById('claim-conf').value),
    asserted_by_id: document.getElementById('claim-asserted').value || undefined,
    source_url: document.getElementById('claim-source-url').value.trim(),
    source_title: document.getElementById('claim-source-title').value.trim(),
    source_author: document.getElementById('claim-source-author').value.trim(),
    source_class: document.getElementById('claim-source-class').value || undefined,
    bias_hint: document.getElementById('claim-bias').value || undefined,
  }};
  if (!body.claim_text) {{ showStatus('claim-status', 'Claim text required', false); return; }}
  fetch('/api/claims', {{method:'POST', headers:{{'Content-Type':'application/json'}}, body: JSON.stringify(body)}})
    .then(r => r.json()).then(d => {{
      if (d.error) {{ showStatus('claim-status', d.error, false); return; }}
      showStatus('claim-status', 'Added claim: ' + d.claim_id, true);
      document.getElementById('claim-text').value = '';
      refreshGraph();
    }});
}}

function addSource() {{
  var body = {{
    url: document.getElementById('src-url').value.trim(),
    title: document.getElementById('src-title').value.trim(),
    author: document.getElementById('src-author').value.trim(),
    platform: document.getElementById('src-platform').value.trim(),
    source_class: document.getElementById('src-class').value || undefined,
    bias_hint: document.getElementById('src-bias').value || undefined,
  }};
  if (!body.url) {{ showStatus('src-status', 'URL required', false); return; }}
  fetch('/api/sources', {{method:'POST', headers:{{'Content-Type':'application/json'}}, body: JSON.stringify(body)}})
    .then(r => r.json()).then(d => {{
      if (d.error) {{ showStatus('src-status', d.error, false); return; }}
      showStatus('src-status', 'Added source: ' + d.id, true);
      document.getElementById('src-url').value = '';
      document.getElementById('src-title').value = '';
      refreshGraph();
    }});
}}

function exportSnapshot() {{
  fetch('/api/export', {{method:'POST'}}).then(r => r.json()).then(d => {{
    if (d.error) {{ showStatus('export-status', d.error, false); return; }}
    showStatus('export-status', 'Exported: ' + JSON.stringify(d.counts), true);
  }});
}}

// Init
populateDropdowns();
initNetwork();
</script>
</body>
</html>
"""


def parse_args(argv=None):
    import argparse as _argparse
    p = _argparse.ArgumentParser(description="Graph enrichment API server for story_graph")
    p.add_argument("--port", type=int, default=8090, help="Port (default: 8090)")
    p.add_argument("--host", default="0.0.0.0", help="Bind address (default: 0.0.0.0)")
    p.add_argument("--db", type=Path, default=Path("data/graph.db"), help="DB path")
    p.add_argument("--snapshot", type=Path, default=Path("graph_snapshot"),
                   help="Snapshot dir for export")
    p.add_argument("--rebuild", action="store_true",
                   help="Rebuild DB from snapshot before starting")
    return p.parse_args(argv)


def main(argv=None):
    global _DB, _SNAPSHOT_DIR
    args = parse_args(argv)
    _SNAPSHOT_DIR = args.snapshot

    if args.rebuild or not args.db.exists():
        print(f"Rebuilding DB from {_SNAPSHOT_DIR}...")
        _DB = import_from_json(_SNAPSHOT_DIR, args.db)
    else:
        _DB = GraphDB(args.db)
        print(f"Opened existing DB: {args.db}")

    # Reopen the connection with check_same_thread=False so Flask's
    # threaded dev server can share the single connection safely.
    _DB.close()
    import sqlite3 as _sqlite3
    _DB._conn = _sqlite3.connect(str(args.db), check_same_thread=False)
    _DB._conn.row_factory = _sqlite3.Row

    print(f"  { _DB.get_node_count()} nodes, {_DB.get_edge_count()} edges, {_DB.get_source_count()} sources")
    print(f"\nStarting server on http://0.0.0.0:{args.port}")
    print(f"  Open http://127.0.0.1:{args.port} in your browser")
    app.run(host=args.host, port=args.port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
