import * as vscode from 'vscode';

const LANGUAGES = ['python','javascript','typescript','java','c','cpp','rust','go'];

export class ConverterPanel {
    static currentPanel: ConverterPanel | undefined;
    private readonly _panel: vscode.WebviewPanel;
    private readonly _port: number;

    static createOrShow(context: vscode.ExtensionContext, port: number) {
        if (ConverterPanel.currentPanel) {
            ConverterPanel.currentPanel._panel.reveal();
            return;
        }
        const panel = vscode.window.createWebviewPanel(
            'codelensConverter',
            'CodeLens AI — Code Converter',
            vscode.ViewColumn.One,
            { enableScripts: true, retainContextWhenHidden: true }
        );
        ConverterPanel.currentPanel = new ConverterPanel(panel, port);
    }

    private constructor(panel: vscode.WebviewPanel, port: number) {
        this._panel = panel;
        this._port = port;
        this._panel.webview.html = this._getHtml();
        this._panel.onDidDispose(() => { ConverterPanel.currentPanel = undefined; });
    }

    private _getHtml(): string {
        const port = this._port;
        const opts = LANGUAGES.map(l => `<option value="${l}">${l}</option>`).join('');
        return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy"
      content="default-src 'none';
               style-src 'unsafe-inline' https://fonts.googleapis.com;
               font-src https://fonts.gstatic.com;
               script-src 'unsafe-inline';
               connect-src http://localhost:${port};">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&display=swap" rel="stylesheet">
<title>Converter</title>
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

/* wave canvas — very faint background texture */
#wave-bg{position:fixed;inset:0;pointer-events:none;z-index:1;opacity:.06;width:100%;height:100%}

/* layout */
.shell{position:relative;z-index:2;display:flex;flex-direction:column;height:100vh}

/* header */
.hdr{display:flex;align-items:center;justify-content:space-between;
  padding:0 18px;height:46px;border-bottom:1px solid var(--border);
  background:rgba(14,14,14,.88);backdrop-filter:blur(6px);flex-shrink:0}
.hdr-brand{font-size:11px;font-weight:600;letter-spacing:.14em;text-transform:uppercase}
.hdr-tag{font-size:9px;letter-spacing:.12em;text-transform:uppercase;
  color:var(--muted);border:1px solid var(--border);padding:3px 9px}

/* editor area */
.editors{flex:1;display:flex;overflow:hidden}

.pane{display:flex;flex-direction:column;flex:1;min-width:0;overflow:hidden}
.pane+.pane{border-left:1px solid var(--border)}

.pane-hdr{display:flex;align-items:center;justify-content:space-between;
  padding:0 14px;height:38px;border-bottom:1px solid var(--border);
  background:rgba(14,14,14,.6);flex-shrink:0}

.pane-label{font-size:9px;letter-spacing:.14em;text-transform:uppercase;color:var(--muted)}

select{appearance:none;-webkit-appearance:none;background:transparent;
  color:var(--text);border:1px solid var(--border);padding:4px 28px 4px 10px;
  font-family:inherit;font-size:11px;letter-spacing:.08em;text-transform:uppercase;
  cursor:pointer;outline:none;
  background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6' viewBox='0 0 10 6'%3E%3Cpath d='M0 0l5 6 5-6z' fill='rgba(255,255,255,0.4)'/%3E%3C/svg%3E");
  background-repeat:no-repeat;background-position:right 8px center}
select option{background:#1a1a1a}

.code-area{flex:1;width:100%;background:transparent;border:none;color:var(--text);
  font-family:'Consolas','SF Mono','Courier New',monospace;font-size:12.5px;
  padding:14px;resize:none;outline:none;line-height:1.6;
  scrollbar-width:thin;scrollbar-color:var(--border) transparent}
.code-area::-webkit-scrollbar{width:3px}
.code-area::-webkit-scrollbar-thumb{background:var(--border)}
.code-area::placeholder{color:var(--muted)}
.code-area[readonly]{cursor:default}

/* bottom toolbar */
.toolbar{border-top:1px solid var(--border);display:flex;align-items:stretch;
  height:50px;flex-shrink:0;background:rgba(14,14,14,.92)}

#convert{flex:1;background:#fff;color:#0e0e0e;border:none;
  font-family:inherit;font-size:11px;font-weight:700;letter-spacing:.16em;
  text-transform:uppercase;cursor:pointer;transition:opacity .15s}
#convert:hover{opacity:.85}
#convert:disabled{opacity:.35;cursor:not-allowed}

.copy-btn{background:transparent;color:var(--muted);border:none;border-left:1px solid var(--border);
  padding:0 18px;font-family:inherit;font-size:9px;letter-spacing:.12em;
  text-transform:uppercase;cursor:pointer;transition:color .15s;flex-shrink:0}
.copy-btn:hover{color:var(--text)}

.status-strip{border-top:1px solid var(--border);padding:5px 18px;
  font-size:10px;letter-spacing:.08em;color:var(--muted);
  background:rgba(14,14,14,.7);flex-shrink:0;min-height:24px}
</style>
</head>
<body>

<div class="grid"></div>
<canvas id="wave-bg"></canvas>

<div class="shell">
  <div class="hdr">
    <span class="hdr-brand">CodeLens AI &nbsp;/&nbsp; Code Converter</span>
    <span class="hdr-tag">&gt;&gt;&gt;&nbsp;8 LANGUAGES</span>
  </div>

  <div class="editors">
    <!-- Source pane -->
    <div class="pane">
      <div class="pane-hdr">
        <span class="pane-label">Source</span>
        <select id="srcLang">${opts}</select>
      </div>
      <textarea class="code-area" id="srcCode" placeholder="Paste source code here…"></textarea>
    </div>

    <!-- Target pane -->
    <div class="pane">
      <div class="pane-hdr">
        <span class="pane-label">Output</span>
        <select id="tgtLang">${opts}</select>
      </div>
      <textarea class="code-area" id="tgtCode" readonly placeholder="Converted code appears here…"></textarea>
    </div>
  </div>

  <div class="toolbar">
    <button id="convert">&gt;&gt;&gt;&nbsp;&nbsp;CONVERT</button>
    <button class="copy-btn" id="copy">COPY</button>
  </div>

  <div class="status-strip" id="status">&nbsp;</div>
</div>

<script>
// ── Wave background ───────────────────────────────────────────────────────────
(function(){
  var c = document.getElementById('wave-bg');
  var ctx = c.getContext('2d');
  var t = 0;

  function resize(){
    c.width = window.innerWidth;
    c.height = window.innerHeight;
  }
  resize();
  window.addEventListener('resize', resize);

  function frame(){
    ctx.clearRect(0,0,c.width,c.height);
    var waves = 8;
    for(var w=0;w<waves;w++){
      var baseY = (c.height/(waves+1))*(w+1);
      var amp   = 18 + w*4;
      var freq  = 0.012 - w*0.0005;
      var phase = t*(0.6+w*0.12);
      ctx.beginPath();
      ctx.strokeStyle='rgba(255,255,255,.9)';
      ctx.lineWidth=.8;
      for(var x=0;x<=c.width;x+=2){
        var y = baseY + Math.sin(x*freq+phase)*amp + Math.sin(x*freq*1.7+phase*0.8)*amp*0.4;
        x===0 ? ctx.moveTo(x,y) : ctx.lineTo(x,y);
      }
      ctx.stroke();
    }
    t+=0.016;
    requestAnimationFrame(frame);
  }
  frame();
})();

// ── Converter ─────────────────────────────────────────────────────────────────
var srcLang  = document.getElementById('srcLang');
var tgtLang  = document.getElementById('tgtLang');
var srcCode  = document.getElementById('srcCode');
var tgtCode  = document.getElementById('tgtCode');
var convertBtn = document.getElementById('convert');
var copyBtn  = document.getElementById('copy');
var statusEl = document.getElementById('status');

// Default target to javascript
tgtLang.value = 'javascript';

function setStatus(msg){ statusEl.textContent = msg || String.fromCharCode(160); }

convertBtn.addEventListener('click', async function(){
  var code = srcCode.value.trim();
  if(!code){ setStatus('Paste some source code first.'); return; }
  convertBtn.disabled=true;
  convertBtn.textContent='Converting…';
  tgtCode.value='';
  setStatus('Running inference…');
  try{
    var res = await fetch('http://localhost:${port}/convert',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({code:code, source_lang:srcLang.value, target_lang:tgtLang.value})
    });
    var data = await res.json();
    tgtCode.value = data.converted_code ?? JSON.stringify(data,null,2);
    setStatus('Done — ' + srcLang.value + ' → ' + tgtLang.value);
  } catch(e){
    setStatus('Error: cannot reach backend. Is the server running?');
  }
  convertBtn.disabled=false;
  convertBtn.textContent='>>> CONVERT';
});

copyBtn.addEventListener('click', function(){
  if(!tgtCode.value) return;
  navigator.clipboard.writeText(tgtCode.value).then(function(){
    setStatus('Copied to clipboard.');
    setTimeout(function(){ setStatus(''); }, 2000);
  });
});
</script>
</body>
</html>`;
    }
}
