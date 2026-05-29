import * as vscode from 'vscode';

export class GraphPanel {
    static currentPanel: GraphPanel | undefined;
    private readonly _panel: vscode.WebviewPanel;
    private readonly _port: number;

    static createOrShow(context: vscode.ExtensionContext, port: number) {
        if (GraphPanel.currentPanel) {
            GraphPanel.currentPanel._panel.reveal();
            return;
        }
        const panel = vscode.window.createWebviewPanel(
            'codelensGraph',
            'CodeLens AI — Dependency Graph',
            vscode.ViewColumn.One,
            { enableScripts: true, retainContextWhenHidden: true }
        );
        GraphPanel.currentPanel = new GraphPanel(panel, port);
    }

    private constructor(panel: vscode.WebviewPanel, port: number) {
        this._panel = panel;
        this._port = port;
        this._panel.webview.html = this._getHtml();
        this._panel.onDidDispose(() => { GraphPanel.currentPanel = undefined; });
    }

    private _getHtml(): string {
        const port = this._port;
        return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy"
      content="default-src 'none';
               style-src 'unsafe-inline' https://fonts.googleapis.com;
               font-src https://fonts.gstatic.com;
               script-src 'unsafe-inline' https://cdn.jsdelivr.net;
               connect-src http://localhost:${port};">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&display=swap" rel="stylesheet">
<title>Dependency Graph</title>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}

:root{
  --bg:#000000;
  --bg2:#0e0e0e;
  --border:rgba(255,255,255,0.09);
  --border-hi:rgba(255,255,255,0.2);
  --text:#e2e2e2;
  --muted:rgba(255,255,255,0.38);
  --accent:#8b8fc8;
  --accent-dim:rgba(139,143,200,0.15);
  --grid:52px;
  --panel-w:280px;
}

html,body{height:100%;overflow:hidden;background:var(--bg);color:var(--text);
  font-family:'Inter',system-ui,sans-serif;font-size:13px}

/* ── Grid overlay ── */
.grid{position:fixed;inset:0;pointer-events:none;z-index:0;
  background-image:
    linear-gradient(var(--border) 1px,transparent 1px),
    linear-gradient(90deg,var(--border) 1px,transparent 1px);
  background-size:var(--grid) var(--grid)}

/* ── Shell ── */
.shell{position:relative;z-index:2;display:flex;flex-direction:column;height:100vh}

/* ── Header ── */
.hdr{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;
  padding:0 16px;height:46px;border-bottom:1px solid var(--border);
  background:rgba(0,0,0,.92);backdrop-filter:blur(6px);flex-shrink:0;gap:8px}
.hdr-brand{font-size:11px;font-weight:600;letter-spacing:.14em;text-transform:uppercase}
.hdr-right{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.hdr-stat{font-size:9px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted)}

/* ── Toolbar / search ── */
.toolbar{display:flex;align-items:center;gap:8px;flex-wrap:wrap;
  padding:8px 16px;border-bottom:1px solid var(--border);
  background:rgba(0,0,0,.8);flex-shrink:0}

.search-wrap{position:relative;flex:1;min-width:160px;max-width:340px}
.search-wrap input{width:100%;background:transparent;border:1px solid var(--border);
  color:var(--text);padding:5px 10px 5px 30px;font-family:inherit;font-size:11px;
  letter-spacing:.04em;outline:none;transition:border-color .15s}
.search-wrap input:focus{border-color:var(--accent)}
.search-wrap input::placeholder{color:var(--muted)}
.search-icon{position:absolute;left:9px;top:50%;transform:translateY(-50%);
  width:11px;height:11px;opacity:.4}

.filter-group{display:flex;align-items:center;gap:4px;flex-wrap:wrap}
.filter-label{font-size:9px;letter-spacing:.12em;text-transform:uppercase;color:var(--muted)}
.lang-pill{background:transparent;border:1px solid var(--border);color:var(--muted);
  padding:3px 9px;font-family:inherit;font-size:9px;letter-spacing:.08em;text-transform:uppercase;
  cursor:pointer;transition:all .15s;border-radius:2px}
.lang-pill:hover{border-color:var(--border-hi);color:var(--text)}
.lang-pill.active{background:var(--accent-dim);border-color:var(--accent);color:var(--accent)}
.lang-pill.all{border-color:var(--border-hi)}
.lang-pill.all.active{background:rgba(255,255,255,.08);border-color:var(--border-hi);color:var(--text)}

.btn{background:transparent;color:var(--muted);border:1px solid var(--border);
  padding:5px 12px;font-family:inherit;font-size:9px;font-weight:600;
  letter-spacing:.14em;text-transform:uppercase;cursor:pointer;transition:all .15s}
.btn:hover{border-color:var(--border-hi);color:var(--text)}
.btn-solid{background:#fff;color:#000;border-color:#fff;color:#000}
.btn-solid:hover{opacity:.85;color:#000}

/* ── Main body ── */
.body{flex:1;display:flex;overflow:hidden}

/* ── Graph SVG ── */
#graph{flex:1;width:100%;display:block;cursor:grab}
#graph:active{cursor:grabbing}

/* ── Detail panel ── */
.detail{width:0;overflow:hidden;border-left:1px solid var(--border);
  background:rgba(0,0,0,.92);display:flex;flex-direction:column;
  transition:width .25s ease;flex-shrink:0}
.detail.open{width:var(--panel-w)}

.detail-hdr{display:flex;align-items:center;justify-content:space-between;
  padding:12px 14px;border-bottom:1px solid var(--border);flex-shrink:0}
.detail-title{font-size:9px;letter-spacing:.14em;text-transform:uppercase;color:var(--muted)}
.detail-close{background:transparent;border:none;color:var(--muted);cursor:pointer;
  font-size:14px;line-height:1;transition:color .15s;padding:0}
.detail-close:hover{color:var(--text)}

.detail-body{flex:1;overflow-y:auto;padding:14px;
  scrollbar-width:thin;scrollbar-color:var(--border) transparent}
.detail-body::-webkit-scrollbar{width:3px}
.detail-body::-webkit-scrollbar-thumb{background:var(--border)}

.detail-name{font-size:13px;font-weight:600;word-break:break-all;margin-bottom:10px;
  color:var(--accent)}
.detail-lang{display:inline-block;font-size:9px;letter-spacing:.1em;text-transform:uppercase;
  padding:2px 8px;border:1px solid;margin-bottom:14px}

.detail-row{display:flex;justify-content:space-between;align-items:baseline;
  padding:6px 0;border-bottom:1px solid var(--border)}
.detail-row:last-child{border-bottom:none}
.detail-key{font-size:9px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted)}
.detail-val{font-size:11px;color:var(--text);text-align:right}

.detail-section{margin-top:14px}
.detail-section-title{font-size:9px;letter-spacing:.12em;text-transform:uppercase;
  color:var(--muted);margin-bottom:8px;padding-bottom:4px;border-bottom:1px solid var(--border)}
.detail-file-item{font-size:10px;color:var(--muted);padding:3px 0;
  letter-spacing:.02em;word-break:break-all;cursor:pointer;transition:color .15s}
.detail-file-item:hover{color:var(--accent)}

/* ── Zoom controls ── */
.zoom-controls{position:absolute;right:calc(var(--panel-w) + 14px);bottom:50px;
  display:flex;flex-direction:column;gap:4px;transition:right .25s ease}
.detail.open ~ .zoom-controls,
.body:has(.detail.open) .zoom-controls{right:calc(var(--panel-w) + 14px)}
.zoom-btn{background:rgba(0,0,0,.8);color:var(--muted);border:1px solid var(--border);
  width:28px;height:28px;font-family:inherit;font-size:14px;
  cursor:pointer;transition:all .15s;display:flex;align-items:center;justify-content:center}
.zoom-btn:hover{border-color:var(--border-hi);color:var(--text)}

/* ── Tooltip ── */
#tooltip{position:fixed;pointer-events:none;z-index:200;
  background:rgba(0,0,0,.95);border:1px solid var(--border-hi);
  padding:7px 12px;font-size:11px;letter-spacing:.04em;color:var(--text);
  max-width:280px;word-break:break-all;display:none;line-height:1.5}
#tooltip .tt-path{color:var(--accent);font-size:10px;margin-bottom:2px}
#tooltip .tt-stats{color:var(--muted);font-size:9px;letter-spacing:.06em;
  text-transform:uppercase;margin-top:4px}

/* ── Bottom legend ── */
.legend{border-top:1px solid var(--border);padding:7px 16px;
  display:flex;gap:16px;flex-wrap:wrap;background:rgba(0,0,0,.9);flex-shrink:0}
.leg-item{display:flex;align-items:center;gap:5px;
  font-size:9px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted)}
.leg-dot{width:8px;height:8px;border-radius:50%;flex-shrink:0}

/* ── Empty state ── */
.empty{position:absolute;inset:0;display:flex;flex-direction:column;
  align-items:center;justify-content:center;gap:10px;pointer-events:none}
.empty-title{font-size:11px;letter-spacing:.16em;text-transform:uppercase}
.empty-sub{font-size:12px;color:var(--muted);text-align:center;line-height:1.8}

/* ── D3 node styles ── */
.link-line{stroke:rgba(255,255,255,.45);stroke-width:1.5;fill:none;
  transition:stroke .2s,stroke-opacity .2s,stroke-width .2s}
.link-line.highlight{stroke:rgba(139,143,200,.95);stroke-width:2.5}
.link-line.dimmed{stroke-opacity:.07}

.node-circle{stroke-width:1.5;cursor:pointer;transition:all .2s}
.node-circle.dimmed{opacity:.12}
.node-circle.highlight{stroke-width:2.5}

.node-label{font-family:'Inter',system-ui,sans-serif;font-size:10px;
  fill:rgba(255,255,255,.5);pointer-events:none;letter-spacing:.02em;
  transition:fill-opacity .2s}
.node-label.dimmed{fill-opacity:.1}
.node-label.highlight{fill:rgba(255,255,255,.85);fill-opacity:1}
</style>
</head>
<body>

<div class="grid"></div>
<div id="tooltip"><div class="tt-path" id="tt-path"></div><div id="tt-name"></div><div class="tt-stats" id="tt-stats"></div></div>

<div class="shell">
  <!-- Header -->
  <div class="hdr">
    <span class="hdr-brand">CodeLens AI &nbsp;/&nbsp; Dependency Graph</span>
    <div class="hdr-right">
      <span class="hdr-stat" id="stat">—</span>
      <button class="btn btn-solid" id="reload">&gt;&gt;&gt;&nbsp;RELOAD</button>
    </div>
  </div>

  <!-- Toolbar -->
  <div class="toolbar">
    <div class="search-wrap">
      <svg class="search-icon" viewBox="0 0 12 12" fill="none" stroke="rgba(255,255,255,.5)" stroke-width="1.2">
        <circle cx="5" cy="5" r="3.5"/>
        <path d="M8 8l2.5 2.5" stroke-linecap="round"/>
      </svg>
      <input type="text" id="search" placeholder="Search files…" autocomplete="off" spellcheck="false">
    </div>
    <div class="filter-group">
      <span class="filter-label">Lang:</span>
      <button class="lang-pill all active" data-lang="all">All</button>
    </div>
    <button class="btn" id="btnFit">FIT</button>
    <button class="btn" id="btnReset">RESET</button>
  </div>

  <!-- Body: graph + detail panel -->
  <div class="body" style="position:relative">
    <svg id="graph">
      <defs>
        <marker id="arrow" viewBox="0 -4 8 8" refX="18" refY="0"
                markerWidth="6" markerHeight="6" orient="auto">
          <path d="M0,-4L8,0L0,4" fill="rgba(139,143,200,0.35)"/>
        </marker>
      </defs>
    </svg>
    <div id="emptyOverlay" class="empty">
      <div class="empty-title">No graph data</div>
      <div class="empty-sub">Run <strong style="color:var(--text)">Index Workspace</strong><br>from the command palette,<br>then click Reload.</div>
    </div>

    <!-- Zoom buttons overlaid on graph -->
    <div style="position:absolute;right:14px;bottom:50px;display:flex;flex-direction:column;gap:4px;z-index:10" id="zoomBtns">
      <button class="zoom-btn" id="zoomIn">+</button>
      <button class="zoom-btn" id="zoomOut">−</button>
    </div>

    <!-- Detail panel -->
    <div class="detail" id="detailPanel">
      <div class="detail-hdr">
        <span class="detail-title">File Details</span>
        <button class="detail-close" id="detailClose">✕</button>
      </div>
      <div class="detail-body" id="detailBody"></div>
    </div>
  </div>

  <!-- Legend -->
  <div class="legend" id="legend" style="display:none"></div>
</div>

<script src="https://cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js"></script>
<script>
// ── Colour scheme ─────────────────────────────────────────────────────────────
// Base: purple/blue nodes matching reference image; language tints
var LANG_COLORS = {
  python:     '#7b83c4',
  javascript: '#c2a84a',
  typescript: '#6a9fc4',
  java:       '#b07040',
  go:         '#4aa0b8',
  rust:       '#c47850',
  c:          '#9090a8',
  cpp:        '#b84070',
};
var BASE_NODE = '#8b8fc8';  // default purple — matches reference

function langColor(lang){ return LANG_COLORS[lang] || BASE_NODE; }

// ── State ─────────────────────────────────────────────────────────────────────
var graphData     = null;
var simulation    = null;
var svgSel        = null;
var zoomBehavior  = null;
var gContainer    = null;
var selectedNode  = null;
var activeFilter  = 'all';
var searchQuery   = '';

// ── DOM refs ──────────────────────────────────────────────────────────────────
var tooltip    = document.getElementById('tooltip');
var ttPath     = document.getElementById('tt-path');
var ttName     = document.getElementById('tt-name');
var ttStats    = document.getElementById('tt-stats');
var statEl     = document.getElementById('stat');
var emptyEl    = document.getElementById('emptyOverlay');
var legendEl   = document.getElementById('legend');
var detailEl   = document.getElementById('detailPanel');
var detailBody = document.getElementById('detailBody');
var searchEl   = document.getElementById('search');

// ── Load graph ────────────────────────────────────────────────────────────────
async function loadGraph(){
  statEl.textContent = 'Loading…';
  try{
    var res = await fetch('http://localhost:${port}/graph');
    if(!res.ok){
      statEl.textContent = 'No graph — index first';
      emptyEl.style.display = 'flex';
      return;
    }
    graphData = await res.json();

    // Pre-compute degree for node sizing
    var degree = {};
    graphData.nodes.forEach(function(n){ degree[n.id] = 0; });
    graphData.links.forEach(function(l){
      var s = typeof l.source === 'object' ? l.source.id : l.source;
      var t = typeof l.target === 'object' ? l.target.id : l.target;
      degree[s] = (degree[s]||0)+1;
      degree[t] = (degree[t]||0)+1;
    });
    graphData.nodes.forEach(function(n){ n.degree = degree[n.id]||0; });

    emptyEl.style.display = 'none';
    statEl.textContent = graphData.nodes.length+' files  /  '+graphData.links.length+' edges';
    buildLangFilters(graphData.nodes);
    buildLegend(graphData.nodes);
    renderGraph();
  } catch(e){
    statEl.textContent = 'Backend unreachable';
    emptyEl.style.display = 'flex';
  }
}

// ── Lang filter pills ─────────────────────────────────────────────────────────
function buildLangFilters(nodes){
  var langs = {};
  nodes.forEach(function(n){ if(n.language) langs[n.language]=true; });
  var group = document.querySelector('.filter-group');
  // Remove old pills (keep label + All)
  Array.from(group.querySelectorAll('.lang-pill:not(.all)')).forEach(function(p){ p.remove(); });
  Object.keys(langs).sort().forEach(function(lang){
    var pill = document.createElement('button');
    pill.className = 'lang-pill';
    pill.dataset.lang = lang;
    pill.textContent = lang;
    pill.style.borderColor = langColor(lang)+'88';
    pill.addEventListener('click', function(){ setFilter(lang); });
    group.appendChild(pill);
  });
}

function setFilter(lang){
  activeFilter = lang;
  document.querySelectorAll('.lang-pill').forEach(function(p){
    p.classList.toggle('active', p.dataset.lang === lang);
  });
  applyFilters();
}

document.querySelector('.lang-pill.all').addEventListener('click', function(){ setFilter('all'); });

// ── Legend ────────────────────────────────────────────────────────────────────
function buildLegend(nodes){
  var seen = {};
  nodes.forEach(function(n){ if(n.language) seen[n.language]=true; });
  legendEl.innerHTML = '';
  Object.keys(seen).sort().forEach(function(lang){
    var item = document.createElement('div');
    item.className = 'leg-item';
    var dot = document.createElement('div');
    dot.className = 'leg-dot';
    dot.style.background = langColor(lang);
    item.appendChild(dot);
    item.appendChild(document.createTextNode(lang));
    legendEl.appendChild(item);
  });
  legendEl.style.display = 'flex';
}

// ── Node radius based on degree ────────────────────────────────────────────────
function nodeRadius(d){
  var base = 5;
  var r = base + Math.sqrt(d.degree||0) * 2.5;
  return Math.min(r, 22); // cap at 22
}

// ── Render graph ──────────────────────────────────────────────────────────────
function renderGraph(){
  svgSel = d3.select('#graph');
  svgSel.selectAll('*').remove();

  var W = svgSel.node().clientWidth  || 800;
  var H = svgSel.node().clientHeight || 500;

  // Deep-copy nodes/links for simulation (prevents mutation on re-render)
  var nodes = graphData.nodes.map(function(d){ return Object.assign({}, d); });
  var links = graphData.links.map(function(d){
    return { source: d.source, target: d.target };
  });

  zoomBehavior = d3.zoom()
    .scaleExtent([0.08, 6])
    .on('zoom', function(e){ gContainer.attr('transform', e.transform); });
  svgSel.call(zoomBehavior);

  gContainer = svgSel.append('g');

  simulation = d3.forceSimulation(nodes)
    .force('link', d3.forceLink(links).id(function(d){ return d.id; })
      .distance(function(d){
        // Short links for tightly-coupled files
        return 70 + (nodeRadius(d.source)+nodeRadius(d.target)) * 2;
      })
      .strength(0.4))
    .force('charge', d3.forceManyBody()
      .strength(function(d){ return -120 - d.degree*8; }))
    .force('center', d3.forceCenter(W/2, H/2))
    .force('collision', d3.forceCollide(function(d){ return nodeRadius(d)+8; }));

  // ── Links ──
  var linkSel = gContainer.append('g')
    .selectAll('line')
    .data(links)
    .join('line')
    .attr('class','link-line');

  // ── Nodes ──
  var nodeSel = gContainer.append('g')
    .selectAll('g')
    .data(nodes)
    .join('g')
    .attr('class','node-g')
    .call(d3.drag()
      .on('start', function(e,d){
        if(!e.active) simulation.alphaTarget(.3).restart();
        d.fx=d.x; d.fy=d.y;
      })
      .on('drag', function(e,d){ d.fx=e.x; d.fy=e.y; })
      .on('end',  function(e,d){
        if(!e.active) simulation.alphaTarget(0);
        d.fx=null; d.fy=null;
      }));

  nodeSel.append('circle')
    .attr('class','node-circle')
    .attr('r', nodeRadius)
    .attr('fill', function(d){ return langColor(d.language); })
    .attr('fill-opacity', .82)
    .attr('stroke', function(d){ return langColor(d.language); })
    .attr('stroke-opacity', .5);

  nodeSel.append('text')
    .attr('class','node-label')
    .attr('x', function(d){ return nodeRadius(d)+5; })
    .attr('dy','0.35em')
    .text(function(d){ return d.label; });

  // ── Interactions ──
  nodeSel
    .on('mousemove', function(e,d){
      tooltip.style.display = 'block';
      tooltip.style.left = (e.clientX+16)+'px';
      tooltip.style.top  = (e.clientY-10)+'px';
      var dir = d.id.replace(/\\\\/g,'/');
      var parts = dir.split('/');
      var name = parts.pop();
      ttPath.textContent = parts.join('/') || '/';
      ttName.textContent = name;
      ttStats.textContent = 'imports: '+d.degree+' connections · '+d.language;
    })
    .on('mouseleave', function(){ tooltip.style.display='none'; })
    .on('click', function(e,d){
      e.stopPropagation();
      selectNode(d, nodeSel, linkSel);
    });

  // Click on background deselects
  svgSel.on('click', function(){ clearSelection(nodeSel, linkSel); });

  simulation.on('tick', function(){
    linkSel
      .attr('x1',function(d){ return d.source.x; })
      .attr('y1',function(d){ return d.source.y; })
      .attr('x2',function(d){ return d.target.x; })
      .attr('y2',function(d){ return d.target.y; });
    nodeSel.attr('transform',function(d){ return 'translate('+d.x+','+d.y+')'; });
  });

  // Store refs for filter/search use
  window._nodeSel = nodeSel;
  window._linkSel = linkSel;

  applyFilters();
}

// ── Node selection + highlight ────────────────────────────────────────────────
function selectNode(d, nodeSel, linkSel){
  selectedNode = d;

  var connectedIds = new Set([d.id]);
  linkSel.each(function(l){
    var s = l.source.id || l.source;
    var t = l.target.id || l.target;
    if(s===d.id || t===d.id){ connectedIds.add(s); connectedIds.add(t); }
  });

  nodeSel.select('circle')
    .attr('class', function(n){
      return 'node-circle' + (connectedIds.has(n.id) ? ' highlight' : ' dimmed');
    });
  nodeSel.select('text')
    .attr('class', function(n){
      return 'node-label' + (connectedIds.has(n.id) ? ' highlight' : ' dimmed');
    });
  linkSel
    .attr('class', function(l){
      var s = l.source.id||l.source, t = l.target.id||l.target;
      if(s===d.id||t===d.id) return 'link-line highlight';
      return 'link-line dimmed';
    });

  showDetail(d, connectedIds);
}

function clearSelection(nodeSel, linkSel){
  selectedNode = null;
  nodeSel.select('circle').attr('class','node-circle');
  nodeSel.select('text').attr('class','node-label');
  linkSel.attr('class','link-line');
  applyFilters(); // re-apply dim if filter active
  hideDetail();
}

// ── Detail panel ──────────────────────────────────────────────────────────────
function showDetail(d, connectedIds){
  // Count imports / imported-by from current graph
  var importsOut = [], importsIn = [];
  if(graphData){
    graphData.links.forEach(function(l){
      var s = typeof l.source==='object'?l.source.id:l.source;
      var t = typeof l.target==='object'?l.target.id:l.target;
      if(s===d.id) importsOut.push(t);
      if(t===d.id) importsIn.push(s);
    });
  }

  var color = langColor(d.language);
  detailBody.innerHTML = '';

  var name = document.createElement('div');
  name.className = 'detail-name';
  name.textContent = d.label;
  detailBody.appendChild(name);

  var langBadge = document.createElement('div');
  langBadge.className = 'detail-lang';
  langBadge.style.borderColor = color;
  langBadge.style.color = color;
  langBadge.textContent = d.language || 'unknown';
  detailBody.appendChild(langBadge);

  function row(key, val){
    var r = document.createElement('div');
    r.className = 'detail-row';
    r.innerHTML = '<span class="detail-key">'+key+'</span><span class="detail-val">'+val+'</span>';
    detailBody.appendChild(r);
  }

  var pathParts = d.id.replace(/\\\\/g,'/').split('/');
  pathParts.pop();
  row('Directory', pathParts.join('/') || '/');
  row('Imports', importsOut.length+' files');
  row('Imported by', importsIn.length+' files');
  row('Total edges', d.degree);

  function section(title, items, label){
    if(!items.length) return;
    var s = document.createElement('div');
    s.className = 'detail-section';
    s.innerHTML = '<div class="detail-section-title">'+title+'</div>';
    items.slice(0,15).forEach(function(id){
      var item = document.createElement('div');
      item.className = 'detail-file-item';
      item.textContent = id.replace(/\\\\/g,'/').split('/').pop();
      item.title = id;
      item.addEventListener('click', function(){
        // Jump to that node
        if(!graphData || !window._nodeSel) return;
        var found = null;
        window._nodeSel.each(function(n){ if(n.id===id) found=n; });
        if(found) selectNode(found, window._nodeSel, window._linkSel);
      });
      s.appendChild(item);
    });
    if(items.length>15){
      var more = document.createElement('div');
      more.className='detail-file-item';more.style.color='var(--muted)';
      more.textContent='+ '+(items.length-15)+' more…';
      s.appendChild(more);
    }
    detailBody.appendChild(s);
  }

  section('Imports →', importsOut, 'imports');
  section('← Imported by', importsIn, 'imported-by');

  detailEl.classList.add('open');
}

function hideDetail(){
  detailEl.classList.remove('open');
  detailBody.innerHTML = '';
}

document.getElementById('detailClose').addEventListener('click', function(){
  if(window._nodeSel) clearSelection(window._nodeSel, window._linkSel);
  hideDetail();
});

// ── Filter + search ────────────────────────────────────────────────────────────
function applyFilters(){
  if(!window._nodeSel || !window._linkSel) return;

  var query = searchQuery.trim().toLowerCase();

  window._nodeSel.each(function(d){
    var langMatch  = activeFilter==='all' || d.language===activeFilter;
    var searchMatch= !query || d.id.toLowerCase().includes(query) ||
                     d.label.toLowerCase().includes(query);
    var visible    = langMatch && searchMatch;
    d3.select(this).select('circle').attr('fill-opacity', visible ? .82 : .07);
    d3.select(this).select('text').attr('fill-opacity', visible ? null : .06);
  });

  window._linkSel.attr('stroke-opacity', function(l){
    var s = l.source.id||l.source, t = l.target.id||l.target;
    var sNode = graphData.nodes.find(function(n){ return n.id===s; });
    var tNode = graphData.nodes.find(function(n){ return n.id===t; });
    if(!sNode||!tNode) return .04;
    var sOk = (activeFilter==='all'||sNode.language===activeFilter) &&
              (!query||sNode.id.toLowerCase().includes(query)||sNode.label.toLowerCase().includes(query));
    var tOk = (activeFilter==='all'||tNode.language===activeFilter) &&
              (!query||tNode.id.toLowerCase().includes(query)||tNode.label.toLowerCase().includes(query));
    return (sOk&&tOk) ? .13 : .02;
  });
}

searchEl.addEventListener('input', function(){
  searchQuery = searchEl.value;
  applyFilters();
});

// ── Zoom controls ─────────────────────────────────────────────────────────────
document.getElementById('zoomIn').addEventListener('click', function(){
  if(svgSel) svgSel.transition().duration(300).call(zoomBehavior.scaleBy, 1.4);
});
document.getElementById('zoomOut').addEventListener('click', function(){
  if(svgSel) svgSel.transition().duration(300).call(zoomBehavior.scaleBy, 0.7);
});
document.getElementById('btnFit').addEventListener('click', function(){
  if(!svgSel||!gContainer) return;
  var W=svgSel.node().clientWidth, H=svgSel.node().clientHeight;
  var bb = gContainer.node().getBBox();
  if(!bb.width||!bb.height) return;
  var scale = Math.min(.9*W/bb.width, .9*H/bb.height, 2);
  var tx = W/2 - scale*(bb.x+bb.width/2);
  var ty = H/2 - scale*(bb.y+bb.height/2);
  svgSel.transition().duration(500)
    .call(zoomBehavior.transform, d3.zoomIdentity.translate(tx,ty).scale(scale));
});
document.getElementById('btnReset').addEventListener('click', function(){
  if(selectedNode && window._nodeSel) clearSelection(window._nodeSel, window._linkSel);
  setFilter('all');
  searchEl.value=''; searchQuery='';
  if(svgSel) svgSel.transition().duration(400).call(zoomBehavior.transform, d3.zoomIdentity);
  applyFilters();
});

// ── Reload ────────────────────────────────────────────────────────────────────
document.getElementById('reload').addEventListener('click', loadGraph);

// ── Init ──────────────────────────────────────────────────────────────────────
loadGraph();
</script>
</body>
</html>`;
    }
}
