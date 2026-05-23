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
  --bg:#0e0e0e;
  --border:rgba(255,255,255,0.1);
  --border-hi:rgba(255,255,255,0.22);
  --text:#e2e2e2;
  --muted:rgba(255,255,255,0.35);
  --grid:52px;
}

html,body{height:100%;overflow:hidden;background:var(--bg);color:var(--text);
  font-family:'Inter',system-ui,sans-serif;font-size:13px}

/* grid */
.grid{position:fixed;inset:0;pointer-events:none;z-index:0;
  background-image:
    linear-gradient(var(--border) 1px,transparent 1px),
    linear-gradient(90deg,var(--border) 1px,transparent 1px);
  background-size:var(--grid) var(--grid)}

/* layout */
.shell{position:relative;z-index:2;display:flex;flex-direction:column;height:100vh}

/* header */
.hdr{display:flex;align-items:center;justify-content:space-between;
  padding:0 18px;height:46px;border-bottom:1px solid var(--border);
  background:rgba(14,14,14,.9);backdrop-filter:blur(6px);flex-shrink:0}
.hdr-brand{font-size:11px;font-weight:600;letter-spacing:.14em;text-transform:uppercase}
.hdr-right{display:flex;align-items:center;gap:10px}
.hdr-stat{font-size:9px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted)}

.btn{background:transparent;color:var(--text);border:1px solid var(--border);
  padding:5px 14px;font-family:inherit;font-size:9px;font-weight:600;
  letter-spacing:.14em;text-transform:uppercase;cursor:pointer;transition:all .15s}
.btn:hover{border-color:var(--border-hi);background:rgba(255,255,255,.04)}
.btn-solid{background:#fff;color:#0e0e0e;border-color:#fff}
.btn-solid:hover{opacity:.85;background:#fff}

/* graph canvas */
#graph{flex:1;width:100%;display:block}

/* tooltip */
#tooltip{position:fixed;pointer-events:none;z-index:100;
  background:rgba(14,14,14,.95);border:1px solid var(--border-hi);
  padding:7px 12px;font-size:11px;letter-spacing:.04em;color:var(--text);
  max-width:280px;word-break:break-all;display:none}

/* legend */
.legend{border-top:1px solid var(--border);padding:8px 18px;
  display:flex;gap:18px;flex-wrap:wrap;background:rgba(14,14,14,.9);flex-shrink:0}
.leg-item{display:flex;align-items:center;gap:6px;
  font-size:9px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted)}
.leg-dot{width:8px;height:8px;border-radius:50%;flex-shrink:0}

/* empty state */
.empty-overlay{position:absolute;inset:0;display:flex;flex-direction:column;
  align-items:center;justify-content:center;gap:12px;pointer-events:none}
.empty-title{font-size:11px;letter-spacing:.16em;text-transform:uppercase}
.empty-sub{font-size:12px;color:var(--muted);text-align:center;line-height:1.7}

/* D3 styles */
.link{stroke:rgba(255,255,255,.18);stroke-width:1;fill:none}
.node circle{stroke-width:1.5;cursor:pointer;transition:r .15s}
.node circle:hover{r:9}
.node text{font-family:'Inter',system-ui,sans-serif;font-size:10px;
  fill:rgba(255,255,255,.55);pointer-events:none;letter-spacing:.02em}
</style>
</head>
<body>

<div class="grid"></div>
<div id="tooltip"></div>

<div class="shell">
  <div class="hdr">
    <span class="hdr-brand">CodeLens AI &nbsp;/&nbsp; Dependency Graph</span>
    <div class="hdr-right">
      <span class="hdr-stat" id="stat">—</span>
      <button class="btn" id="reload">&gt;&gt;&gt;&nbsp;RELOAD</button>
    </div>
  </div>

  <svg id="graph">
    <div class="empty-overlay" id="empty">
      <div class="empty-title">No graph data</div>
      <div class="empty-sub">Run <strong style="color:var(--text)">Index Workspace</strong><br>then reload.</div>
    </div>
  </svg>

  <div class="legend" id="legend" style="display:none"></div>
</div>

<script src="https://cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js"></script>
<script>
var LANG_COLORS = {
  python:    '#5a8fcc',
  javascript:'#c9b840',
  typescript:'#3d8fa8',
  java:      '#9a6622',
  go:        '#2b9eb3',
  rust:      '#c47a50',
  c:         '#888888',
  cpp:       '#c44060',
};
var DEFAULT_COLOR = 'rgba(255,255,255,0.5)';

var tooltip = document.getElementById('tooltip');
var statEl  = document.getElementById('stat');
var emptyEl = document.getElementById('empty');
var legendEl= document.getElementById('legend');

function langColor(lang){
  var c = LANG_COLORS[lang];
  if(!c) return DEFAULT_COLOR;
  // desaturate a bit for the dark aesthetic
  return c;
}

function buildLegend(nodes){
  var seen = {};
  nodes.forEach(function(n){ if(n.language) seen[n.language]=true; });
  legendEl.innerHTML='';
  Object.keys(seen).sort().forEach(function(lang){
    var item = document.createElement('div');
    item.className='leg-item';
    var dot = document.createElement('div');
    dot.className='leg-dot';
    dot.style.background=langColor(lang);
    item.appendChild(dot);
    item.appendChild(document.createTextNode(lang));
    legendEl.appendChild(item);
  });
  legendEl.style.display='flex';
}

async function loadGraph(){
  statEl.textContent='Loading…';
  try{
    var res = await fetch('http://localhost:${port}/graph');
    if(!res.ok){
      statEl.textContent='No graph — index first';
      emptyEl.style.display='flex';
      return;
    }
    var data = await res.json();
    emptyEl.style.display='none';
    statEl.textContent=data.nodes.length+' files  /  '+data.links.length+' deps';
    renderGraph(data);
    buildLegend(data.nodes);
  } catch(e){
    statEl.textContent='Backend unreachable';
    emptyEl.style.display='flex';
  }
}

function renderGraph(data){
  var svg = d3.select('#graph');
  svg.selectAll('*').remove();

  var W = svg.node().clientWidth;
  var H = svg.node().clientHeight;

  var sim = d3.forceSimulation(data.nodes)
    .force('link', d3.forceLink(data.links).id(function(d){return d.id;}).distance(90))
    .force('charge', d3.forceManyBody().strength(-180))
    .force('center', d3.forceCenter(W/2, H/2))
    .force('collision', d3.forceCollide(14));

  var g = svg.append('g');

  svg.call(d3.zoom()
    .scaleExtent([0.2,4])
    .on('zoom', function(e){ g.attr('transform', e.transform); }));

  // links
  var link = g.append('g')
    .selectAll('line')
    .data(data.links)
    .join('line')
    .attr('class','link');

  // nodes
  var node = g.append('g')
    .selectAll('g')
    .data(data.nodes)
    .join('g')
    .attr('class','node')
    .call(d3.drag()
      .on('start',function(e,d){ if(!e.active) sim.alphaTarget(.3).restart(); d.fx=d.x;d.fy=d.y; })
      .on('drag', function(e,d){ d.fx=e.x;d.fy=e.y; })
      .on('end',  function(e,d){ if(!e.active) sim.alphaTarget(0); d.fx=null;d.fy=null; }));

  node.append('circle')
    .attr('r',6)
    .attr('fill', function(d){ return langColor(d.language); })
    .attr('fill-opacity',.85)
    .attr('stroke', function(d){ return langColor(d.language); })
    .attr('stroke-opacity',.4);

  node.append('text')
    .attr('x',10)
    .attr('dy','0.35em')
    .text(function(d){ return d.label; });

  // tooltip
  node
    .on('mousemove', function(e,d){
      tooltip.style.display='block';
      tooltip.style.left=(e.clientX+14)+'px';
      tooltip.style.top=(e.clientY-8)+'px';
      tooltip.textContent=d.id+' ('+d.language+')';
    })
    .on('mouseleave', function(){
      tooltip.style.display='none';
    });

  sim.on('tick', function(){
    link
      .attr('x1',function(d){return d.source.x;})
      .attr('y1',function(d){return d.source.y;})
      .attr('x2',function(d){return d.target.x;})
      .attr('y2',function(d){return d.target.y;});
    node.attr('transform',function(d){return 'translate('+d.x+','+d.y+')';});
  });
}

document.getElementById('reload').addEventListener('click', loadGraph);
loadGraph();
</script>
</body>
</html>`;
    }
}
