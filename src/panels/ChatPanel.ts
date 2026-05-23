import * as vscode from 'vscode';

export class ChatPanel {
    static currentPanel: ChatPanel | undefined;
    private readonly _panel: vscode.WebviewPanel;
    private readonly _port: number;

    static createOrShow(context: vscode.ExtensionContext, port: number) {
        if (ChatPanel.currentPanel) {
            ChatPanel.currentPanel._panel.reveal();
            return;
        }
        const panel = vscode.window.createWebviewPanel(
            'codelensChat',
            'CodeLens AI — Chat',
            vscode.ViewColumn.One,
            { enableScripts: true, retainContextWhenHidden: true }
        );
        ChatPanel.currentPanel = new ChatPanel(panel, port);
    }

    private constructor(panel: vscode.WebviewPanel, port: number) {
        this._panel = panel;
        this._port = port;
        this._panel.webview.html = this._getHtml();
        this._panel.onDidDispose(() => { ChatPanel.currentPanel = undefined; });
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
               script-src 'unsafe-inline';
               connect-src http://localhost:${port};">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&display=swap" rel="stylesheet">
<title>Chat</title>
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

/* orbital canvas — centred, very faint */
#orb{position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);
  pointer-events:none;z-index:1;opacity:.09}

/* layout */
.shell{position:relative;z-index:2;display:flex;flex-direction:column;height:100vh}

/* header */
.hdr{display:flex;align-items:center;justify-content:space-between;
  padding:0 18px;height:46px;border-bottom:1px solid var(--border);
  background:rgba(14,14,14,.88);backdrop-filter:blur(6px);flex-shrink:0}
.hdr-brand{font-size:11px;font-weight:600;letter-spacing:.14em;text-transform:uppercase}
.hdr-tag{font-size:9px;letter-spacing:.12em;text-transform:uppercase;
  color:var(--muted);border:1px solid var(--border);padding:3px 9px}

/* messages */
#msgs{flex:1;overflow-y:auto;padding:20px 18px;display:flex;flex-direction:column;gap:14px;
  scrollbar-width:thin;scrollbar-color:var(--border) transparent}
#msgs::-webkit-scrollbar{width:3px}
#msgs::-webkit-scrollbar-thumb{background:var(--border)}

.msg{display:flex;flex-direction:column;gap:5px;max-width:88%}
.msg-lbl{font-size:9px;letter-spacing:.12em;text-transform:uppercase;color:var(--muted)}
.msg-body{padding:11px 14px;border:1px solid var(--border);line-height:1.65;font-size:13px}

.msg.user{align-self:flex-end;align-items:flex-end}
.msg.user .msg-body{background:rgba(255,255,255,.05);border-color:var(--border-hi)}
.msg.ai .msg-body{border-left:2px solid #fff}
.msg.err .msg-body{border-left:2px solid #e05555;color:#f08080}

.msg-body pre{background:rgba(255,255,255,.04);border:1px solid var(--border);
  padding:9px 12px;margin:7px 0;overflow-x:auto;border-radius:0}
.msg-body code{font-family:'Consolas','SF Mono',monospace;font-size:11.5px;
  background:rgba(255,255,255,.06);padding:1px 5px}
.msg-body pre code{background:none;padding:0}
.msg-body strong{color:#fff}

/* empty state */
.empty{flex:1;display:flex;flex-direction:column;align-items:center;
  justify-content:center;gap:10px;color:var(--muted);text-align:center;padding:24px}
.empty-title{font-size:11px;letter-spacing:.16em;text-transform:uppercase;color:var(--text)}
.empty-sub{font-size:12px;line-height:1.7;max-width:300px}

/* input */
.inp-wrap{border-top:1px solid var(--border);background:rgba(14,14,14,.92);flex-shrink:0}
.inp-row{display:flex;align-items:stretch}
#inp{flex:1;background:transparent;border:none;color:var(--text);
  font-family:inherit;font-size:13px;padding:14px 18px;resize:none;
  min-height:50px;max-height:130px;outline:none;line-height:1.55}
#inp::placeholder{color:var(--muted)}
#send{background:#fff;color:#0e0e0e;border:none;border-left:1px solid var(--border);
  padding:0 22px;font-family:inherit;font-size:10px;font-weight:700;
  letter-spacing:.14em;text-transform:uppercase;cursor:pointer;flex-shrink:0;
  transition:opacity .15s}
#send:hover{opacity:.8}
#send:disabled{opacity:.3;cursor:not-allowed}
</style>
</head>
<body>

<div class="grid"></div>
<canvas id="orb" width="560" height="320"></canvas>

<div class="shell">
  <div class="hdr">
    <span class="hdr-brand">CodeLens AI &nbsp;/&nbsp; Chat</span>
    <span class="hdr-tag">&gt;&gt;&gt;&nbsp;LOCAL LLM</span>
  </div>

  <div id="msgs">
    <div class="empty">
      <div class="empty-title">Codebase intelligence &mdash; fully offline</div>
      <div class="empty-sub">Run <strong>Index Workspace</strong> first,<br>then ask anything about your code.</div>
    </div>
  </div>

  <div class="inp-wrap">
    <div class="inp-row">
      <textarea id="inp" rows="1" placeholder="Ask anything about the codebase…"></textarea>
      <button id="send">&gt;&gt;&gt;</button>
    </div>
  </div>
</div>

<script>
// ── Orbital animation ─────────────────────────────────────────────────────────
(function(){
  var c = document.getElementById('orb');
  var ctx = c.getContext('2d');
  var W = 560, H = 320, t = 0;
  function frame(){
    ctx.clearRect(0,0,W,H);
    ctx.strokeStyle = 'rgba(255,255,255,.95)';
    ctx.lineWidth = .65;
    var cx=W/2, cy=H/2, maxRx=220, ry=78, N=24;
    for(var i=0;i<N;i++){
      var phase=(i/N)*Math.PI+t;
      var rx=maxRx*Math.abs(Math.cos(phase));
      ctx.beginPath();
      ctx.ellipse(cx,cy,Math.max(rx,.4),ry,0,0,Math.PI*2);
      ctx.stroke();
    }
    ctx.fillStyle='rgba(255,255,255,.95)';
    ctx.beginPath();ctx.arc(W/2,H/2,4.5,0,Math.PI*2);ctx.fill();
    t+=.0025;
    requestAnimationFrame(frame);
  }
  frame();
})();

// ── Chat ──────────────────────────────────────────────────────────────────────
var msgsEl = document.getElementById('msgs');
var inpEl  = document.getElementById('inp');
var sendBtn= document.getElementById('send');
var populated = false;

// Markdown without backtick regex (TypeScript template literal safe)
var T3 = String.fromCharCode(96,96,96);
var T1 = String.fromCharCode(96);

function renderMd(raw){
  function esc(s){ return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;') }
  var parts = raw.split(T3);
  var out = '';
  for(var i=0;i<parts.length;i++){
    if(i%2===1){
      var code = parts[i].replace(/^[a-z]*\\n/,'');
      out += '<pre><code>'+esc(code)+'</code></pre>';
    } else {
      var inlineRe = new RegExp(T1+'([^'+T1+'\\n]+)'+T1,'g');
      var s = esc(parts[i])
        .replace(inlineRe,'<code>$1</code>')
        .replace(/\\*\\*([^*]+)\\*\\*/g,'<strong>$1</strong>')
        .replace(/\\n/g,'<br>');
      out += s;
    }
  }
  return out;
}

function addMsg(role, html){
  if(!populated){
    msgsEl.innerHTML='';
    populated=true;
  }
  var wrap = document.createElement('div');
  wrap.className='msg '+role;
  var lbl = role==='user'?'You':role==='ai'?'CodeLens AI':'Error';
  wrap.innerHTML='<div class="msg-lbl">'+lbl+'</div><div class="msg-body">'+html+'</div>';
  msgsEl.appendChild(wrap);
  msgsEl.scrollTop=msgsEl.scrollHeight;
  return wrap;
}

async function doSend(){
  var q = inpEl.value.trim();
  if(!q) return;
  inpEl.value='';
  inpEl.style.height='auto';
  addMsg('user', q.replace(/&/g,'&amp;').replace(/</g,'&lt;'));
  sendBtn.disabled=true;

  var thinkWrap = addMsg('ai','<span style="color:var(--muted)">thinking…</span>');

  try{
    var res = await fetch('http://localhost:${port}/chat',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({query:q,top_k:5})
    });
    var data = await res.json();
    thinkWrap.querySelector('.msg-body').innerHTML = renderMd(data.answer ?? JSON.stringify(data));
  } catch(e){
    thinkWrap.className='msg err';
    thinkWrap.querySelector('.msg-lbl').textContent='Error';
    thinkWrap.querySelector('.msg-body').textContent='Cannot reach backend — is the server running?';
  }
  sendBtn.disabled=false;
  inpEl.focus();
}

sendBtn.addEventListener('click', doSend);
inpEl.addEventListener('keydown', function(e){
  if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();doSend();}
});
inpEl.addEventListener('input', function(){
  this.style.height='auto';
  this.style.height=Math.min(this.scrollHeight,130)+'px';
});
</script>
</body>
</html>`;
    }
}
