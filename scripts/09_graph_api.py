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

from flask import Flask, abort, jsonify, request, send_file

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.crawler.image_capture import DEFAULT_IMAGES_DIR, image_path_for, thumb_path_for
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

# Matches the image node id scheme from scripts/_pipeline_helpers.py
# ("image:<sha256>") — validated before touching the filesystem so a
# crafted node id can't be used for path traversal.
_CONTENT_HASH_RE = re.compile(r"^[0-9a-f]{64}$")

app = Flask(__name__, static_folder=None)

# Global DB handle — opened in main(), reused across requests.
# Flask's dev server is single-threaded by default so this is safe.
_DB: GraphDB | None = None
_SNAPSHOT_DIR: Path = Path("graph_snapshot")
_NODE_COLORS = {
    "Person": "#e74c3c", "Group": "#3498db", "Place": "#2ecc71",
    "Event": "#f39c12", "Work": "#9b59b6", "Claim": "#95a5a6",
    "Image": "#16a085",
}
_EDGE_COLORS = {
    "FOUNDED": "#e74c3c", "WORKED_AT": "#3498db", "MEMBER_OF": "#1abc9c",
    "MENTIONS": "#95a5a6", "ABOUT": "#bdc3c7", "DESCRIBES": "#f39c12",
    "CONTAINS": "#3498db", "ASSERTED_BY": "#e67e22", "SUPPORTED_BY": "#2ecc71",
    "CONTRADICTS": "#e74c3c", "CREATED": "#9b59b6", "LIVED_AT": "#1abc9c",
    "LOCATED_IN": "#2ecc71", "DEPICTS": "#16a085",
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


def _image_counts_by_node(db: GraphDB) -> dict[str, int]:
    """Count DEPICTS edges per source node, for the has_images/image_count badge.

    Image nodes themselves are never drawn on the canvas (they'd add
    hundreds of grey dots for what the user actually wants — an
    indicator + thumbnail gallery on the node they illustrate) so this
    is computed server-side and folded into the regular node payload.
    """
    counts: dict[str, int] = {}
    for e in db.get_all_edges():
        if e.rel_type == RelationType.DEPICTS:
            counts[e.src_id] = counts.get(e.src_id, 0) + 1
    return counts


@app.route("/api/graph")
def api_graph():
    """Return all nodes, edges, sources as JSON for vis.js.

    Image nodes are excluded from the canvas payload (see
    _image_counts_by_node); every other node gets a has_images flag
    and image_count so the UI can render a badge.
    """
    db = get_db()
    image_counts = _image_counts_by_node(db)
    nodes = []
    for n in db.get_all_nodes():
        ntype = n.type.value
        if ntype == "Image":
            continue
        img_count = image_counts.get(n.id, 0)
        not_connected = bool(n.metadata.get("not_connected"))
        label = n.label[:50] + (" \U0001f5bc" if img_count else "")
        nodes.append({
            "id": n.id,
            "label": label,
            "group": ntype,
            "has_images": img_count > 0,
            "image_count": img_count,
            "not_connected": not_connected,
            "title": json.dumps({
                "id": n.id, "type": ntype, "label": n.label,
                "metadata": n.metadata, "source_urls": n.source_urls,
                "image_count": img_count,
            }, default=str),
            "color": {"background": _NODE_COLORS.get(ntype, "#bdc3c7"),
                      "border": "#34495e"},
            "font": {"size": 10},
        })
    edges = []
    for e in db.get_all_edges():
        if e.rel_type == RelationType.DEPICTS:
            continue
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


@app.route("/api/node/<path:node_id>/mark_not_connected", methods=["POST"])
def api_mark_not_connected(node_id: str):
    """Mark a node as not connected to the core information graph.

    The node is retained (to prevent rescraping) but flagged so it cannot
    contribute to the confidence or veracity of any claims. Sets
    metadata["not_connected"] = True with a timestamp.
    """
    db = get_db()
    node = db.get_node(node_id)
    if node is None:
        return jsonify({"error": "not found"}), 404
    meta = {**node.metadata, "not_connected": True, "not_connected_set_at": _now_iso()}
    _update_node_metadata(db, node, meta)
    return jsonify({"ok": True, "id": node_id, "not_connected": True})


@app.route("/api/node/<path:node_id>/unmark_not_connected", methods=["POST"])
def api_unmark_not_connected(node_id: str):
    """Remove the not_connected flag from a node, restoring it to the core graph."""
    db = get_db()
    node = db.get_node(node_id)
    if node is None:
        return jsonify({"error": "not found"}), 404
    meta = {k: v for k, v in node.metadata.items()
            if k not in ("not_connected", "not_connected_set_at")}
    _update_node_metadata(db, node, meta)
    return jsonify({"ok": True, "id": node_id, "not_connected": False})


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _update_node_metadata(db: GraphDB, node: GraphNode, meta: dict) -> None:
    """Update a node's metadata in-place, preserving label/canonical/urls."""
    db._get_conn().execute(
        "UPDATE nodes SET metadata_json = ? WHERE id = ?",
        (json.dumps(meta), node.id),
    )
    db._get_conn().commit()


@app.route("/api/export", methods=["POST"])
def api_export():
    """Persist the in-memory DB to graph_snapshot/ JSONL files."""
    db = get_db()
    counts = export_to_json(db, _SNAPSHOT_DIR)
    return jsonify({"ok": True, "counts": counts})


def _degree_map(db: GraphDB) -> dict[str, int]:
    """Count edges per node (both in and out), for ranking connections."""
    deg: dict[str, int] = {}
    for e in db.get_all_edges():
        if e.rel_type == RelationType.DEPICTS:
            continue
        deg[e.src_id] = deg.get(e.src_id, 0) + 1
        deg[e.dst_id] = deg.get(e.dst_id, 0) + 1
    return deg


@app.route("/api/node/<path:node_id>")
def api_node_detail(node_id: str):
    """Get full details for a single node, including connected edges.

    Each edge includes the connected node's degree (for ranking by
    connectivity) and metadata (for temporal proximity sorting — e.g.
    events with start_date/end_date).
    """
    db = get_db()
    node = db.get_node(node_id)
    if node is None:
        return jsonify({"error": "not found"}), 404
    deg = _degree_map(db)
    edges_out = []
    images = []
    for e in db.get_edges_from(node_id):
        dst = db.get_node(e.dst_id)
        if e.rel_type == RelationType.DEPICTS and dst is not None:
            images.append(_image_summary(dst))
            continue
        edges_out.append({"rel_type": e.rel_type.value, "dst_id": e.dst_id,
                          "dst_label": dst.label if dst else "?",
                          "dst_type": dst.type.value if dst else "?",
                          "dst_metadata": dst.metadata if dst else {},
                          "degree": deg.get(e.dst_id, 0),
                          "direction": "out"})
    for e in db.get_edges_to(node_id):
        src = db.get_node(e.src_id)
        edges_out.append({"rel_type": e.rel_type.value, "src_id": e.src_id,
                          "src_label": src.label if src else "?",
                          "src_type": src.type.value if src else "?",
                          "src_metadata": src.metadata if src else {},
                          "degree": deg.get(e.src_id, 0),
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
        "images": images,
        "claims": [{"id": c.id, "label": c.label,
                     "metadata": c.metadata} for c in claims],
    })


def _image_summary(image_node: GraphNode) -> dict:
    """Build the JSON shape the sidebar gallery/lightbox needs for one Image node."""
    meta = image_node.metadata
    content_hash = meta.get("content_hash", "")
    return {
        "id": image_node.id,
        "thumb_url": f"/media/thumb/{content_hash}",
        "full_url": f"/media/image/{content_hash}",
        "alt": meta.get("alt", ""),
        "width": meta.get("width"),
        "height": meta.get("height"),
        "source_urls": image_node.source_urls,
    }


@app.route("/media/thumb/<content_hash>")
def media_thumb(content_hash: str):
    """Serve a generated thumbnail, addressed by content hash (never by path)."""
    if not _CONTENT_HASH_RE.match(content_hash):
        abort(400)
    path = thumb_path_for(content_hash, DEFAULT_IMAGES_DIR)
    if not path.exists():
        abort(404)
    return send_file(path, mimetype="image/jpeg")


@app.route("/media/image/<content_hash>")
def media_image(content_hash: str):
    """Serve the original captured image, addressed by content hash."""
    if not _CONTENT_HASH_RE.match(content_hash):
        abort(400)
    for ext in (".jpg", ".png", ".gif", ".webp", ".bmp", ".img"):
        path = image_path_for(content_hash, ext, DEFAULT_IMAGES_DIR)
        if path.exists():
            return send_file(path)
    abort(404)


# --- Visualization HTML ---

def _build_viz_html() -> str:
    """Build the interactive visualization HTML with enrichment forms."""
    db = get_db()
    n_nodes = db.get_node_count()
    n_edges = db.get_edge_count()
    n_sources = db.get_source_count()

    # Get all node IDs for the edge form dropdowns (Image nodes are internal
    # bookkeeping, not something a reviewer should link claims/edges to)
    all_nodes = [n for n in db.get_all_nodes() if n.type != NodeType.IMAGE]
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
<!-- Multi-CDN fallback for Cytoscape.js: try unpkg, then jsdelivr, then cdnjs.
     If all fail, the diagnostic panel shows the error and a fallback table
     view is rendered instead of a blank canvas. -->
<script>
var CYTOSCAPE_LOADED = false;
var CYTOSCAPE_SOURCE = null;
function _tryLoadCytoscape(srcs, idx) {{
  if (idx >= srcs.length) {{
    diag.error('Cytoscape.js failed to load from all CDNs: ' + srcs.join(', '));
    diag.set('library', 'FAILED (all CDNs unreachable)');
    renderFallbackTable();
    return;
  }}
  var s = document.createElement('script');
  s.src = srcs[idx];
  s.onload = function() {{
    if (typeof cytoscape !== 'undefined') {{
      CYTOSCAPE_LOADED = true;
      CYTOSCAPE_SOURCE = srcs[idx];
      diag.set('library', 'Cytoscape.js loaded from ' + srcs[idx].split('/')[2]);
      diag.log('Cytoscape.js loaded successfully from ' + srcs[idx]);
      initGraph();
    }} else {{
      diag.warn('Script loaded but cytoscape undefined from ' + srcs[idx]);
      _tryLoadCytoscape(srcs, idx + 1);
    }}
  }};
  s.onerror = function() {{
    diag.warn('CDN failed: ' + srcs[idx]);
    _tryLoadCytoscape(srcs, idx + 1);
  }};
  document.head.appendChild(s);
}}
</script>
<style>
body {{ font-family: sans-serif; margin: 0; padding: 0; }}
#network {{ width: 65%; height: calc(100vh - 30px); float: left; position: relative; }}
#sidebar {{ width: 35%; height: calc(100vh - 30px); float: right; overflow-y: auto;
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
.conn-link {{ color: #2980b9; cursor: pointer; text-decoration: none; }}
.conn-link:hover {{ text-decoration: underline; color: #3498db; }}
.node-actions {{ display: flex; gap: 4px; margin: 6px 0; flex-wrap: wrap; }}
.node-actions button {{ padding: 3px 8px; font-size: 11px; border: 1px solid #ccc;
                        border-radius: 3px; cursor: pointer; }}
.btn-warn {{ background: #e74c3c; color: white; border-color: #c0392b; }}
.btn-warn:hover {{ background: #c0392b; }}
.btn-restore {{ background: #2ecc71; color: white; border-color: #27ae60; }}
.btn-restore:hover {{ background: #27ae60; }}
.not-connected-banner {{ background: #fdf2f2; border: 1px solid #e74c3c; border-radius: 4px;
                         padding: 6px 8px; margin: 6px 0; font-size: 11px; color: #c0392b; }}
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
.btn-sm {{ padding: 3px 8px; font-size: 11px; }}
.status {{ font-size: 11px; padding: 4px; margin: 4px 0; border-radius: 3px; }}
.status.ok {{ background: #d4edda; color: #155724; }}
.status.err {{ background: #f8d7da; color: #721c24; }}
.image-gallery {{ display: flex; flex-wrap: wrap; gap: 6px; margin: 6px 0; }}
.image-gallery img {{ width: 72px; height: 72px; object-fit: cover;
                      border-radius: 4px; border: 1px solid #ccc; cursor: pointer;
                      background: #eee; }}
.image-gallery img:hover {{ border-color: #16a085; }}
#lightbox {{ display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.85);
             z-index: 1000; align-items: center; justify-content: center;
             flex-direction: column; }}
#lightbox.open {{ display: flex; }}
#lightbox img {{ max-width: 90vw; max-height: 80vh; border-radius: 4px; }}
#lightbox .caption {{ color: #eee; font-size: 12px; margin-top: 8px; max-width: 80vw;
                       text-align: center; }}
#lightbox .caption a {{ color: #7fd6ff; }}
#lightbox-close {{ position: absolute; top: 16px; right: 24px; color: #fff;
                    font-size: 24px; cursor: pointer; }}
/* --- Diagnostic bar --- */
#diag-bar {{ position: fixed; bottom: 0; left: 0; right: 0; height: 24px;
             background: #2c3e50; color: #ecf0f1; font-size: 11px;
             display: flex; align-items: center; padding: 0 8px; gap: 12px;
             z-index: 999; font-family: monospace; }}
#diag-bar .diag-item {{ white-space: nowrap; }}
#diag-bar .diag-ok {{ color: #2ecc71; }}
#diag-bar .diag-warn {{ color: #f39c12; }}
#diag-bar .diag-err {{ color: #e74c3c; }}
#diag-toggle {{ cursor: pointer; margin-left: auto; text-decoration: underline; }}
#diag-panel {{ display: none; position: fixed; bottom: 24px; right: 0; width: 400px;
               max-height: 300px; overflow-y: auto; background: #1a1a2e; color: #a0a0b0;
               font-size: 11px; font-family: monospace; padding: 8px; z-index: 1001;
               border: 1px solid #444; }}
#diag-panel.open {{ display: block; }}
#diag-panel .log-line {{ margin: 2px 0; }}
#diag-panel .log-err {{ color: #e74c3c; }}
#diag-panel .log-warn {{ color: #f39c12; }}
#diag-panel .log-ok {{ color: #2ecc71; }}
/* --- Loading overlay --- */
#loading-overlay {{ position: absolute; inset: 0; background: rgba(255,255,255,0.9);
                    display: flex; align-items: center; justify-content: center;
                    flex-direction: column; z-index: 100; }}
#loading-overlay.hidden {{ display: none; }}
.spinner {{ width: 40px; height: 40px; border: 4px solid #ddd;
            border-top: 4px solid #3498db; border-radius: 50%;
            animation: spin 1s linear infinite; }}
@keyframes spin {{ 0% {{ transform: rotate(0deg); }} 100% {{ transform: rotate(360deg); }} }}
/* --- Fallback table --- */
#fallback-view {{ display: none; padding: 16px; overflow-y: auto; height: 100%; }}
#fallback-view table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
#fallback-view th, #fallback-view td {{ padding: 4px 8px; border-bottom: 1px solid #eee; text-align: left; }}
#fallback-view th {{ background: #f0f0f0; cursor: pointer; }}
/* --- Graph controls --- */
.graph-controls {{ position: absolute; top: 8px; left: 8px; z-index: 50;
                   display: flex; gap: 4px; flex-wrap: wrap; }}
.graph-controls select, .graph-controls button {{
  padding: 3px 8px; font-size: 11px; border: 1px solid #ccc; border-radius: 3px; }}
</style>
</head>
<body>
<div id="network">
  <div id="loading-overlay">
    <div class="spinner"></div>
    <p style="margin-top:12px;color:#555">Loading graph data…</p>
  </div>
  <div class="graph-controls" id="graph-controls" style="display:none">
    <select id="layout-select" onchange="changeLayout()"
            title="Layout algorithm — how nodes are arranged on the canvas. Concentric: highest-degree nodes in the center. COSE: force-directed (spreads connected nodes apart). Circle: ring. Grid: regular grid. Breadth-first: tree by edge direction.">
      <option value="concentric">Concentric (by degree)</option>
      <option value="cose">Force-directed (COSE)</option>
      <option value="circle">Circle</option>
      <option value="grid">Grid</option>
      <option value="breadthfirst">Breadth-first</option>
    </select>
    <button class="btn-sm" onclick="fitGraph()"
            title="Fit — zoom the canvas to show all visible nodes (keyboard: double-click background also fits).">Fit</button>
    <button class="btn-sm" id="filter-toggle" onclick="toggleFilter()"
            title="Degree filter — for large graphs (>800 nodes), toggles between showing all nodes and only the top 100 by connection count. Auto-enabled on load for large graphs to keep rendering responsive.">Show all</button>
    <button class="btn-sm" id="images-toggle" onclick="toggleImagesOnly()"
            title="Images only — show only nodes that have associated images (the 🖼 badge). Click again to return to the previous view. Combined with the degree filter, this shows the most-connected illustrated nodes.">Images only</button>
    <button class="btn-sm" id="precedes-toggle" onclick="togglePrecedesEdges()"
            title="PRECEDES edges — temporal ordering between events. Hidden by default because they create O(n²) hairball (7K+ edges). Click to show them.">PRECEDES: hidden</button>
  </div>
  <div id="fallback-view">
    <h3>Graph rendering unavailable — fallback node list</h3>
    <p style="font-size:12px;color:#666">Cytoscape.js could not be loaded. See diagnostic panel for details.</p>
    <input id="fallback-search" type="text" placeholder="Filter…" oninput="filterFallback()"
           style="width:100%;padding:4px;margin-bottom:8px">
    <table id="fallback-table"><thead><tr><th>Type</th><th>Label</th><th>ID</th></tr></thead><tbody></tbody></table>
  </div>
</div>
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
    &nbsp;&nbsp;\U0001f5bc = has images
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

<div id="lightbox" onclick="closeLightbox(event)">
  <span id="lightbox-close" onclick="closeLightbox(event)">&times;</span>
  <img id="lightbox-img" src="">
  <div class="caption" id="lightbox-caption"></div>
</div>

<!-- Diagnostic bar + expandable panel -->
<div id="diag-bar">
  <span class="diag-item" id="diag-library">library: …</span>
  <span class="diag-item" id="diag-data">data: …</span>
  <span class="diag-item" id="diag-render">render: …</span>
  <span class="diag-item" id="diag-nodes">nodes: …</span>
  <span class="diag-toggle" onclick="toggleDiagPanel()">diagnostics ▾</span>
</div>
<div id="diag-panel"></div>

<script>
// ============================================================
// Diagnostic system — logs every step of graph initialization
// so failures are never silent. The bar at the bottom shows
// live status; the expandable panel shows the full log.
// ============================================================
var diag = (function() {{
  var entries = [];
  var panel = document.getElementById('diag-panel');
  var bar = {{
    library: document.getElementById('diag-library'),
    data: document.getElementById('diag-data'),
    render: document.getElementById('diag-render'),
    nodes: document.getElementById('diag-nodes'),
  }};
  function _cls(level) {{ return level === 'error' ? 'diag-err' : level === 'warn' ? 'diag-warn' : 'diag-ok'; }}
  function _logCls(level) {{ return level === 'error' ? 'log-err' : level === 'warn' ? 'log-warn' : 'log-ok'; }}
  function _push(level, msg) {{
    var ts = new Date().toLocaleTimeString();
    entries.push({{ts: ts, level: level, msg: msg}});
    if (panel) {{
      var div = document.createElement('div');
      div.className = 'log-line ' + _logCls(level);
      div.textContent = '[' + ts + '] ' + level.toUpperCase() + ': ' + msg;
      panel.appendChild(div);
      panel.scrollTop = panel.scrollHeight;
    }}
    if (level === 'error') console.error('[diag] ' + msg);
    else if (level === 'warn') console.warn('[diag] ' + msg);
    else console.log('[diag] ' + msg);
  }}
  return {{
    log: function(msg) {{ _push('info', msg); }},
    ok: function(msg) {{ _push('ok', msg); }},
    warn: function(msg) {{ _push('warn', msg); }},
    error: function(msg) {{ _push('error', msg); }},
    set: function(key, val) {{
      if (bar[key]) {{ bar[key].textContent = key + ': ' + val; bar[key].className = 'diag-item ' + _cls('ok'); }}
    }},
    setWarn: function(key, val) {{
      if (bar[key]) {{ bar[key].textContent = key + ': ' + val; bar[key].className = 'diag-item ' + _cls('warn'); }}
    }},
    setErr: function(key, val) {{
      if (bar[key]) {{ bar[key].textContent = key + ': ' + val; bar[key].className = 'diag-item ' + _cls('err'); }}
    }},
    getEntries: function() {{ return entries; }},
  }};
}})();

function toggleDiagPanel() {{ document.getElementById('diag-panel').classList.toggle('open'); }}

// ============================================================
// Graph data + Cytoscape.js rendering
// ============================================================
var allNodeOptions = {node_options};
var allSourceOptions = {source_options};
var graphData = null;       // raw API response
var cy = null;              // Cytoscape instance
var currentImages = [];
var filteredMode = false;
var imagesOnlyMode = false;
var hidePrecedesEdges = true;  // PRECEDES edges create O(n²) hairball — off by default
var LARGE_GRAPH_THRESHOLD = 800;  // above this, default to top-N by degree
var TOP_N_NODES = 100;            // reduced from 300 — 300 nodes had 10K+ edges

diag.log('Page loaded, starting initialization');
diag.set('library', 'loading…');

// --- Multi-CDN Cytoscape.js loading ---
(function() {{
  var cdns = [
    'https://unpkg.com/cytoscape@3.30.2/dist/cytoscape.min.js',
    'https://cdn.jsdelivr.net/npm/cytoscape@3.30.2/dist/cytoscape.min.js',
    'https://cdnjs.cloudflare.com/ajax/libs/cytoscape/3.30.2/cytoscape.min.js',
  ];
  diag.log('Attempting to load Cytoscape.js from ' + cdns.length + ' CDNs');
  _tryLoadCytoscape(cdns, 0);
}})();

// --- Fallback: searchable HTML table if Cytoscape.js fails ---
function renderFallbackTable() {{
  document.getElementById('loading-overlay').classList.add('hidden');
  document.getElementById('graph-controls').style.display = 'none';
  document.getElementById('fallback-view').style.display = 'block';
  diag.log('Rendering fallback table view');
  fetch('/api/graph').then(function(r) {{ return r.json(); }}).then(function(d) {{
    var tbody = document.querySelector('#fallback-table tbody');
    tbody.innerHTML = '';
    d.nodes.forEach(function(n) {{
      var tr = document.createElement('tr');
      tr.innerHTML = '<td>' + esc(n.group) + '</td><td>' + esc(n.label) + '</td><td>' + esc(n.id) + '</td>';
      tr.onclick = function() {{ showNodeDetail(n.id); }};
      tbody.appendChild(tr);
    }});
    diag.set('nodes', d.counts.nodes + ' nodes');
    diag.set('data', 'OK (fallback)');
  }}).catch(function(e) {{
    diag.setErr('data', 'FETCH FAILED');
    diag.error('Fallback table fetch failed: ' + e);
  }});
}}

function filterFallback() {{
  var q = document.getElementById('fallback-search').value.toLowerCase();
  document.querySelectorAll('#fallback-table tbody tr').forEach(function(tr) {{
    tr.style.display = tr.textContent.toLowerCase().indexOf(q) >= 0 ? '' : 'none';
  }});
}}

// --- Main graph initialization (called after Cytoscape.js loads) ---
function initGraph() {{
  diag.set('data', 'fetching…');
  var t0 = performance.now();
  fetch('/api/graph').then(function(r) {{
    if (!r.ok) throw new Error('HTTP ' + r.status);
    return r.json();
  }}).then(function(d) {{
    var fetchMs = Math.round(performance.now() - t0);
    graphData = d;
    diag.set('data', 'OK (' + fetchMs + 'ms)');
    diag.set('nodes', d.counts.nodes + ' nodes, ' + d.counts.edges + ' edges');
    diag.log('Fetched ' + d.counts.nodes + ' nodes, ' + d.counts.edges + ' edges, ' + d.counts.sources + ' sources in ' + fetchMs + 'ms');
    document.getElementById('counts').textContent =
      d.counts.nodes + ' nodes, ' + d.counts.edges + ' edges, ' + d.counts.sources + ' sources';

    // Auto-degradation: for large graphs, default to top-N nodes by degree
    if (d.counts.nodes > LARGE_GRAPH_THRESHOLD) {{
      diag.warn('Graph has ' + d.counts.nodes + ' nodes (>' + LARGE_GRAPH_THRESHOLD + '), enabling degree filter');
      filteredMode = true;
      document.getElementById('filter-toggle').textContent = 'Show all (' + d.counts.nodes + ')';
    }}

    renderGraph();
  }}).catch(function(e) {{
    diag.setErr('data', 'FETCH FAILED');
    diag.error('Failed to fetch /api/graph: ' + e.message);
    document.getElementById('loading-overlay').innerHTML =
      '<p style="color:#e74c3c">Failed to load graph data: ' + esc(e.message) + '</p>' +
      '<button class="btn" onclick="location.reload()">Retry</button>';
  }});
}}

function _computeDegreeMap(d) {{
  var deg = {{}};
  d.edges.forEach(function(e) {{
    deg[e.from] = (deg[e.from] || 0) + 1;
    deg[e.to] = (deg[e.to] || 0) + 1;
  }});
  return deg;
}}

function renderGraph() {{
  if (!CYTOSCAPE_LOADED || !graphData) {{
    diag.error('renderGraph called but Cytoscape not loaded or no data');
    return;
  }}
  diag.set('render', 'rendering…');
  var t0 = performance.now();
  var d = graphData;
  var deg = _computeDegreeMap(d);

  // Filter to top-N nodes by degree if in filtered mode
  var visibleNodeIds = null;
  if (filteredMode) {{
    var ranked = d.nodes.slice().sort(function(a, b) {{
      return (deg[b.id] || 0) - (deg[a.id] || 0);
    }});
    var topN = ranked.slice(0, TOP_N_NODES);
    visibleNodeIds = new Set(topN.map(function(n) {{ return n.id; }}));
    diag.log('Filtered to top ' + topN.length + ' nodes by degree (max degree=' + (deg[topN[0].id] || 0) + ')');
  }}

  // Images-only filter: intersect visibleNodeIds with nodes that have images.
  // If visibleNodeIds is null (no degree filter), start from all nodes.
  if (imagesOnlyMode) {{
    var withImages = d.nodes.filter(function(n) {{ return n.has_images; }});
    var imgIds = new Set(withImages.map(function(n) {{ return n.id; }}));
    if (visibleNodeIds) {{
      // Intersect with existing degree filter
      var intersected = new Set();
      visibleNodeIds.forEach(function(id) {{ if (imgIds.has(id)) intersected.add(id); }});
      visibleNodeIds = intersected;
    }} else {{
      visibleNodeIds = imgIds;
    }}
    diag.log('Images-only filter: ' + withImages.length + ' nodes have images, ' +
             (visibleNodeIds ? visibleNodeIds.size : 0) + ' visible after combining with degree filter');
  }}

  // Build Cytoscape elements
  var elements = [];
  var nodeColors = {{
    Person: '#e74c3c', Group: '#3498db', Place: '#2ecc71',
    Event: '#f39c12', Work: '#9b59b6', Claim: '#95a5a6',
  }};
  d.nodes.forEach(function(n) {{
    if (visibleNodeIds && !visibleNodeIds.has(n.id)) return;
    elements.push({{
      data: {{
        id: n.id,
        label: n.label,
        group: n.group,
        hasImages: n.has_images,
        imageCount: n.image_count,
        notConnected: n.not_connected,
        degree: deg[n.id] || 0,
      }},
    }});
  }});
  d.edges.forEach(function(e) {{
    if (visibleNodeIds && (!visibleNodeIds.has(e.from) || !visibleNodeIds.has(e.to))) return;
    if (hidePrecedesEdges && e.label === 'PRECEDES') return;
    elements.push({{
      data: {{ source: e.from, target: e.to, label: e.label }},
    }});
  }});

  diag.log('Rendering ' + elements.length + ' elements (' + d.nodes.length + ' total nodes)');

  try {{
    if (cy) {{ cy.destroy(); cy = null; }}
    cy = cytoscape({{
      container: document.getElementById('network'),
      elements: elements,
      style: [
        {{ selector: 'node', style: {{
          'background-color': function(ele) {{ return nodeColors[ele.data('group')] || '#bdc3c7'; }},
          'label': 'data(label)',
          'width': function(ele) {{ var dg = ele.data('degree'); return Math.min(30, 8 + dg * 0.8); }},
          'height': function(ele) {{ var dg = ele.data('degree'); return Math.min(30, 8 + dg * 0.8); }},
          'font-size': '8px',
          'text-valign': 'bottom',
          'text-halign': 'center',
          'text-max-width': '80px',
          'text-wrap': 'ellipsis',
          'color': '#333',
          'border-width': function(ele) {{ return ele.data('hasImages') ? 3 : 0; }},
          'border-color': '#16a085',
        }} }},
        {{ selector: 'node:selected', style: {{
          'border-width': 4, 'border-color': '#2c3e50',
        }} }},
        {{ selector: 'node[notConnected = true]', style: {{
          'background-opacity': 0.15,
          'border-width': 2,
          'border-style': 'dashed',
          'border-color': '#e74c3c',
          'opacity': 0.5,
          'text-opacity': 0.4,
        }} }},
        {{ selector: 'edge', style: {{
          'width': 0.5,
          'line-color': '#bdc3c7',
          'line-opacity': 0.4,
          'target-arrow-color': '#bdc3c7',
          'target-arrow-shape': 'triangle',
          'arrow-scale': 0.6,
          'curve-style': 'bezier',
        }} }},
        {{ selector: 'edge:selected', style: {{
          'line-color': '#e74c3c', 'target-arrow-color': '#e74c3c',
          'width': 2, 'line-opacity': 1,
        }} }},
      ],
      layout: getLayoutOpts(document.getElementById('layout-select').value, deg),
    }});

    cy.on('tap', 'node', function(evt) {{
      showNodeDetail(evt.target.id());
    }});

    document.getElementById('loading-overlay').classList.add('hidden');
    document.getElementById('graph-controls').style.display = 'flex';

    var renderMs = Math.round(performance.now() - t0);
    diag.set('render', 'OK (' + renderMs + 'ms)');
    diag.ok('Graph rendered in ' + renderMs + 'ms');
  }} catch(e) {{
    diag.setErr('render', 'ERROR');
    diag.error('Cytoscape render failed: ' + e.message);
    document.getElementById('loading-overlay').innerHTML =
      '<p style="color:#e74c3c">Render error: ' + esc(e.message) + '</p>' +
      '<button class="btn" onclick="renderFallbackTable()">Use table view</button>';
  }}
}}

function getLayoutOpts(name, deg) {{
  switch(name) {{
    case 'cose':
      return {{ name: 'cose', animate: false, nodeRepulsion: 8000, idealEdgeLength: 50, nodeOverlap: 4, randomize: false }};
    case 'circle':
      return {{ name: 'circle', animate: false }};
    case 'grid':
      return {{ name: 'grid', animate: false }};
    case 'breadthfirst':
      return {{ name: 'breadthfirst', animate: false, directed: true, padding: 10 }};
    case 'concentric':
    default:
      return {{
        name: 'concentric', animate: false,
        concentric: function(ele) {{ return ele.data('degree') || 1; }},
        levelWidth: function() {{ return 2; }},
        minNodeSpacing: 4,
      }};
  }}
}}

function changeLayout() {{
  if (!cy || !graphData) return;
  var name = document.getElementById('layout-select').value;
  var deg = _computeDegreeMap(graphData);
  diag.log('Changing layout to ' + name);
  try {{
    cy.layout(getLayoutOpts(name, deg)).run();
  }} catch(e) {{
    diag.error('Layout "' + name + '" failed: ' + e.message);
  }}
}}

function fitGraph() {{ if (cy) {{ try {{ cy.fit(undefined, 30); }} catch(e) {{ diag.warn('fit failed: ' + e); }} }} }}

function toggleFilter() {{
  filteredMode = !filteredMode;
  var btn = document.getElementById('filter-toggle');
  if (graphData) {{
    btn.textContent = filteredMode ? 'Show all (' + graphData.counts.nodes + ')' : 'Filtered (top ' + TOP_N_NODES + ')';
  }}
  diag.log('Filter toggled: ' + (filteredMode ? 'ON (top ' + TOP_N_NODES + ' by degree)' : 'OFF (all nodes)'));
  renderGraph();
}}

function toggleImagesOnly() {{
  imagesOnlyMode = !imagesOnlyMode;
  var btn = document.getElementById('images-toggle');
  if (btn) {{
    btn.style.background = imagesOnlyMode ? '#16a085' : '';
    btn.style.color = imagesOnlyMode ? 'white' : '';
  }}
  diag.log('Images-only filter toggled: ' + (imagesOnlyMode ? 'ON' : 'OFF'));
  renderGraph();
}}

function togglePrecedesEdges() {{
  hidePrecedesEdges = !hidePrecedesEdges;
  var btn = document.getElementById('precedes-toggle');
  if (btn) {{
    btn.textContent = hidePrecedesEdges ? 'PRECEDES: hidden' : 'PRECEDES: shown';
    btn.style.background = hidePrecedesEdges ? '' : '#f39c12';
    btn.style.color = hidePrecedesEdges ? '' : 'white';
  }}
  diag.log('PRECEDES edges toggled: ' + (hidePrecedesEdges ? 'HIDDEN' : 'SHOWN'));
  renderGraph();
}}

// --- Node detail panel ---

// Extract a sortable date (year as number) from node metadata.
// Checks start_date, end_date, publish_date, date — parses "1969", "1969-05",
// "1969-05-01". Returns null if no date found.
function _extractDate(meta) {{
  if (!meta) return null;
  var fields = ['start_date', 'end_date', 'publish_date', 'date', 'founded_date'];
  for (var i = 0; i < fields.length; i++) {{
    var v = meta[fields[i]];
    if (v) {{
      var m = String(v).match(/^(\\d{{4}})(?:-\\d{{2}})?(?:-\\d{{2}})?/);
      if (m) return parseInt(m[1], 10);
    }}
  }}
  return null;
}}

// Format a date range from metadata for display (e.g. "1969-05" or "1969").
function _formatDateRange(meta) {{
  if (!meta) return '';
  var start = meta.start_date || meta.founded_date || meta.publish_date || meta.date;
  var end = meta.end_date;
  if (!start) return '';
  if (end && end !== start) return String(start).substring(0, 7) + ' to ' + String(end).substring(0, 7);
  return String(start).substring(0, 10);
}}

// Click a connection link: search for the node in the graph, select it,
// and show its detail. If the node isn't currently visible (filtered out),
// turn off filters so it appears, then zoom to it.
function searchNode(nodeId) {{
  // First try to select the node directly if it's on the canvas
  if (cy) {{
    var n = cy.getElementById(nodeId);
    if (n && n.length > 0 && n.isNode()) {{
      cy.animate({{ fit: {{ eles: n.union(n.neighborhood()), padding: 30 }} }}, {{ duration: 400 }});
      cy.$(':selected').unselect();
      n.select();
      showNodeDetail(nodeId);
      return;
    }}
  }}
  // Node not on canvas — clear filters and search by label
  if (filteredMode) {{
    filteredMode = false;
    var btn = document.getElementById('filter-toggle');
    if (btn && graphData) btn.textContent = 'Filtered (top 300)';
  }}
  if (imagesOnlyMode) {{
    imagesOnlyMode = false;
    var ibtn = document.getElementById('images-toggle');
    if (ibtn) {{ ibtn.style.background = ''; ibtn.style.color = ''; }}
  }}
  // Find the node label from graphData to populate the search box
  if (graphData) {{
    var found = null;
    for (var i = 0; i < graphData.nodes.length; i++) {{
      if (graphData.nodes[i].id === nodeId) {{ found = graphData.nodes[i]; break; }}
    }}
    if (found) {{
      var searchInput = document.getElementById('search');
      if (searchInput) {{
        searchInput.value = found.label.replace(/\\s*🖼$/, '').trim();
        filterNodes();
      }}
      // Re-render without filters so the node appears
      renderGraph();
      // After re-render, try to select it (async since renderGraph rebuilds cy)
      setTimeout(function() {{
        if (cy) {{
          var n = cy.getElementById(nodeId);
          if (n && n.length > 0) {{
            cy.animate({{ fit: {{ eles: n.union(n.neighborhood()), padding: 30 }} }}, {{ duration: 400 }});
            cy.$(':selected').unselect();
            n.select();
          }}
        }}
        showNodeDetail(nodeId);
      }}, 300);
      return;
    }}
  }}
  // Fallback: just show detail
  showNodeDetail(nodeId);
}}

// --- Mark/unmark node as not connected to core graph ---
function toggleNotConnected(nodeId, mark) {{
  var endpoint = mark ? 'mark_not_connected' : 'unmark_not_connected';
  fetch('/api/node/' + encodeURIComponent(nodeId) + '/' + endpoint, {{method:'POST'}})
    .then(function(r) {{ return r.json(); }}).then(function(d) {{
      if (d.error) {{
        diag.error('toggleNotConnected failed: ' + d.error);
        return;
      }}
      diag.log('Node ' + nodeId + ' ' + (mark ? 'marked' : 'unmarked') + ' as not_connected');
      // Refresh the detail panel to show the new state
      showNodeDetail(nodeId);
      // Refresh the graph to update node styling
      refreshGraph();
    }}).catch(function(e) {{
      diag.error('toggleNotConnected fetch failed: ' + e.message);
    }});
}}

function showNodeDetail(nodeId) {{
  fetch('/api/node/' + encodeURIComponent(nodeId)).then(function(r) {{ return r.json(); }}).then(function(d) {{
    var n = d.node;
    var isNC = n.metadata && n.metadata.not_connected;
    var html = '<h4>' + esc(n.label) + '</h4>';
    html += '<p><b>ID:</b> ' + esc(n.id) + '<br><b>Type:</b> ' + esc(n.type) + '</p>';
    // Not-connected banner + action menu
    if (isNC) {{
      html += '<div class="not-connected-banner"><b>⚠ Not connected to core graph</b><br>' +
              'This node is retained to prevent rescraping but cannot contribute to ' +
              'claim confidence or veracity.';
      if (n.metadata.not_connected_set_at)
        html += '<br>Marked: ' + esc(n.metadata.not_connected_set_at);
      html += '</div>';
    }}
    html += '<div class="node-actions">';
    if (isNC) {{
      html += '<button class="btn-restore" onclick="toggleNotConnected(\\'' + esc(nodeId) + '\\', false)">Restore to core graph</button>';
    }} else {{
      html += '<button class="btn-warn" onclick="toggleNotConnected(\\'' + esc(nodeId) + '\\', true)">Mark as not connected</button>';
    }}
    html += '</div>';
    if (n.metadata && Object.keys(n.metadata).length > 0)
      html += '<pre>' + esc(JSON.stringify(n.metadata, null, 2)) + '</pre>';
    if (n.source_urls && n.source_urls.length > 0) {{
      html += '<p><b>Source URLs:</b><br>';
      n.source_urls.forEach(function(u) {{
        html += '<a href="' + esc(u) + '" target="_blank">' + esc(u) + '</a><br>';
      }});
      html += '</p>';
    }}
    currentImages = d.images || [];
    if (currentImages.length > 0) {{
      html += '<p><b>Images (' + currentImages.length + '):</b></p><div class="image-gallery">';
      currentImages.forEach(function(img, i) {{
        html += '<img src="' + esc(img.thumb_url) + '" alt="' + esc(img.alt || '') +
                '" loading="lazy" onclick="openLightbox(' + i + ')" ' +
                "onerror=\\"this.style.visibility='hidden'\\" />";
      }});
      html += '</div>';
    }}
    html += '<p><b>Connections (' + d.edges.length + '):</b></p>';
    // Rank by degree (most connected first), then by temporal proximity
    // to the current node (closest in time first). Show top 20.
    var nodeDate = _extractDate(n.metadata);
    var ranked = d.edges.slice().sort(function(a, b) {{
      var aDeg = a.degree || 0, bDeg = b.degree || 0;
      if (bDeg !== aDeg) return bDeg - aDeg;
      // Tie-break by temporal proximity if we have a date for the current node
      if (nodeDate) {{
        var aMeta = a.direction === 'out' ? a.dst_metadata : a.src_metadata;
        var bMeta = b.direction === 'out' ? b.dst_metadata : b.src_metadata;
        var aDate = _extractDate(aMeta);
        var bDate = _extractDate(bMeta);
        if (aDate && bDate) {{
          var aDiff = Math.abs(aDate - nodeDate);
          var bDiff = Math.abs(bDate - nodeDate);
          return aDiff - bDiff;
        }}
        // Nodes with dates rank above nodes without
        if (aDate && !bDate) return -1;
        if (!aDate && bDate) return 1;
      }}
      return 0;
    }});
    var shown = ranked.slice(0, 20);
    html += '<ul class="edge-list">';
    shown.forEach(function(e) {{
      var otherId, otherLabel, otherType;
      if (e.direction === 'out') {{
        otherId = e.dst_id; otherLabel = e.dst_label; otherType = e.dst_type;
        html += '<li>' + esc(e.rel_type) + ' &rarr; ';
      }} else {{
        otherId = e.src_id; otherLabel = e.src_label; otherType = e.src_type;
        html += '<li>';
      }}
      var deg = e.degree || 0;
      var dateStr = _formatDateRange(e.direction === 'out' ? e.dst_metadata : e.src_metadata);
      var otherMeta = e.direction === 'out' ? e.dst_metadata : e.src_metadata;
      var otherNC = otherMeta && otherMeta.not_connected;
      var ncMark = otherNC ? ' <span style="color:#e74c3c;font-size:10px" title="Not connected to core graph">⚠N/C</span>' : '';
      html += '<a class="conn-link" onclick="searchNode(\\'' + esc(otherId).replace(/'/g, "\\'") + '\\')" ' +
              'title="Click to find this node on the graph (degree: ' + deg + (dateStr ? ', date: ' + dateStr : '') + (otherNC ? ', NOT CONNECTED' : '') + ')">' +
              esc(otherLabel) + '</a>' + ncMark;
      if (e.direction === 'in')
        html += ' &rarr; ' + esc(e.rel_type);
      html += ' <span style="color:#999;font-size:10px">(' + deg + ' connections' + (dateStr ? ', ' + dateStr : '') + ')</span>';
      html += '</li>';
    }});
    html += '</ul>';
    if (d.edges.length > 20)
      html += '<p style="font-size:11px;color:#666">Showing top 20 of ' + d.edges.length + ' by connectivity' +
              (nodeDate ? ' + temporal proximity' : '') + '.</p>';
    if (d.claims.length > 0) {{
      if (isNC) {{
        html += '<p style="font-size:11px;color:#c0392b"><b>Claims below are from a node marked not connected — ' +
                'their confidence/veracity should not be relied upon.</b></p>';
      }}
      html += '<p><b>Claims (' + d.claims.length + '):</b></p><ul class="edge-list">';
      d.claims.forEach(function(c) {{
        var claimConf = c.metadata.confidence || '?';
        if (isNC) claimConf = claimConf + ' [N/C]';
        html += '<li>[' + esc(c.metadata.stance||'?') + ', conf=' + esc(String(claimConf)) +
                '] ' + esc(c.label.substring(0,80)) + '</li>';
      }});
      html += '</ul>';
    }}
    document.getElementById('detail').innerHTML = html;
  }}).catch(function(e) {{
    document.getElementById('detail').innerHTML = '<p style="color:#e74c3c">Failed to load details: ' + esc(e.message) + '</p>';
    diag.error('showNodeDetail fetch failed for ' + nodeId + ': ' + e.message);
  }});
}}

// --- Search/filter ---
function filterNodes() {{
  var q = document.getElementById('search').value.toLowerCase();
  if (!cy) return;
  if (q.length === 0) {{
    cy.elements().style('opacity', 1);
    return;
  }}
  cy.elements().style('opacity', 0.1);
  var matched = cy.nodes().filter(function(n) {{
    return (n.data('label') || '').toLowerCase().indexOf(q) >= 0;
  }});
  matched.style('opacity', 1);
  matched.neighborhood().style('opacity', 1);
  if (matched.length > 0) {{ try {{ cy.animate({{ fit: {{ eles: matched.union(matched.neighborhood()), padding: 30 }} }}, {{ duration: 300 }}); }} catch(e) {{}} }}
}}

// --- Lightbox ---
function openLightbox(i) {{
  var img = currentImages[i];
  if (!img) return;
  document.getElementById('lightbox-img').src = img.full_url;
  var cap = esc(img.alt || '(no caption)');
  if (img.source_urls && img.source_urls.length > 0) {{
    cap += ' &middot; <a href="' + esc(img.source_urls[0]) + '" target="_blank">source</a>';
  }}
  document.getElementById('lightbox-caption').innerHTML = cap;
  document.getElementById('lightbox').classList.add('open');
}}
function closeLightbox(e) {{
  if (e && e.target && e.target.id === 'lightbox-img') return;
  document.getElementById('lightbox').classList.remove('open');
}}

// --- HTML escape (prevents XSS from crawled alt text / labels) ---
function esc(s) {{
  if (!s) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}}

// --- Tabs ---
function showTab(name) {{
  document.querySelectorAll('.tab').forEach(function(t) {{ t.classList.remove('active'); }});
  document.querySelectorAll('.tab-content').forEach(function(c) {{ c.classList.remove('active'); }});
  event.target.classList.add('active');
  document.getElementById('tab-' + name).classList.add('active');
}}

// --- Dropdowns ---
function populateDropdowns() {{
  var edgeSrc = document.getElementById('edge-src');
  var edgeDst = document.getElementById('edge-dst');
  var claimAbout = document.getElementById('claim-about');
  var claimAsserted = document.getElementById('claim-asserted');
  if (!edgeSrc) return;
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
    if (n.type !== 'Claim') {{
      var opt3 = document.createElement('option');
      opt3.value = n.id; opt3.text = '[' + n.type + '] ' + n.label;
      claimAbout.appendChild(opt3);
    }}
  }});
}}
populateDropdowns();

// --- Enrichment API calls ---
function showStatus(id, msg, ok) {{
  var el = document.getElementById(id);
  if (!el) return;
  el.innerHTML = '<div class="status ' + (ok ? 'ok' : 'err') + '">' + esc(msg) + '</div>';
  setTimeout(function() {{ el.innerHTML = ''; }}, 5000);
}}

function refreshGraph() {{
  if (!CYTOSCAPE_LOADED) {{ renderFallbackTable(); return; }}
  fetch('/api/graph').then(function(r) {{ return r.json(); }}).then(function(d) {{
    graphData = d;
    if (cy) {{ cy.destroy(); cy = null; }}
    document.getElementById('loading-overlay').classList.remove('hidden');
    renderGraph();
    document.getElementById('counts').textContent =
      d.counts.nodes + ' nodes, ' + d.counts.edges + ' edges, ' + d.counts.sources + ' sources';
    allNodeOptions = d.nodes.map(function(n) {{
      return {{ id: n.id, label: n.label, type: n.group }};
    }});
    document.getElementById('edge-src').innerHTML = '';
    document.getElementById('edge-dst').innerHTML = '';
    document.getElementById('claim-about').innerHTML = '';
    document.getElementById('claim-asserted').innerHTML = '<option value="">— none —</option>';
    populateDropdowns();
  }}).catch(function(e) {{
    diag.error('refreshGraph fetch failed: ' + e.message);
    showStatus('node-status', 'Refresh failed: ' + e.message, false);
  }});
}}

function addNode() {{
  var meta = document.getElementById('node-meta').value.trim();
  var body = {{
    type: document.getElementById('node-type').value,
    label: document.getElementById('node-label').value.trim(),
    source_urls: document.getElementById('node-urls').value.split(',').map(function(s){{return s.trim();}}).filter(Boolean),
  }};
  if (meta) {{ try {{ body.metadata = JSON.parse(meta); }} catch(e) {{
    showStatus('node-status', 'Invalid JSON metadata', false); return; }} }}
  fetch('/api/nodes', {{method:'POST', headers:{{'Content-Type':'application/json'}}, body: JSON.stringify(body)}})
    .then(function(r) {{ return r.json(); }}).then(function(d) {{
      if (d.error) {{ showStatus('node-status', d.error, false); return; }}
      showStatus('node-status', 'Added: ' + d.id, true);
      document.getElementById('node-label').value = '';
      document.getElementById('node-meta').value = '';
      document.getElementById('node-urls').value = '';
      refreshGraph();
    }}).catch(function(e) {{ showStatus('node-status', 'Error: ' + e.message, false); }});
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
    .then(function(r) {{ return r.json(); }}).then(function(d) {{
      if (d.error) {{ showStatus('edge-status', d.error, false); return; }}
      showStatus('edge-status', 'Added edge: ' + body.rel_type, true);
      refreshGraph();
    }}).catch(function(e) {{ showStatus('edge-status', 'Error: ' + e.message, false); }});
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
    .then(function(r) {{ return r.json(); }}).then(function(d) {{
      if (d.error) {{ showStatus('claim-status', d.error, false); return; }}
      showStatus('claim-status', 'Added claim: ' + d.claim_id, true);
      document.getElementById('claim-text').value = '';
      refreshGraph();
    }}).catch(function(e) {{ showStatus('claim-status', 'Error: ' + e.message, false); }});
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
    .then(function(r) {{ return r.json(); }}).then(function(d) {{
      if (d.error) {{ showStatus('src-status', d.error, false); return; }}
      showStatus('src-status', 'Added source: ' + d.id, true);
      document.getElementById('src-url').value = '';
      document.getElementById('src-title').value = '';
      refreshGraph();
    }}).catch(function(e) {{ showStatus('src-status', 'Error: ' + e.message, false); }});
}}

function exportSnapshot() {{
  fetch('/api/export', {{method:'POST'}}).then(function(r) {{ return r.json(); }}).then(function(d) {{
    if (d.error) {{ showStatus('export-status', d.error, false); return; }}
    showStatus('export-status', 'Exported: ' + JSON.stringify(d.counts), true);
  }}).catch(function(e) {{ showStatus('export-status', 'Error: ' + e.message, false); }});
}}

// Global error catch-all — any uncaught error shows in the diagnostic panel
window.addEventListener('error', function(e) {{
  diag.error('Uncaught: ' + (e.message || 'unknown error') + (e.filename ? ' (' + e.filename.split('/').pop() + ':' + e.lineno + ')' : ''));
}});
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
