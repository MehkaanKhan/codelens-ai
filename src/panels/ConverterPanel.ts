import * as vscode from 'vscode';

const LANGUAGES = ['python','javascript','typescript','java','c','cpp','rust','go'];

const EXT_TO_LANG: Record<string, string> = {
    '.py': 'python', '.js': 'javascript', '.ts': 'typescript',
    '.java': 'java', '.c': 'c', '.cpp': 'cpp', '.cc': 'cpp', '.cxx': 'cpp',
    '.rs': 'rust', '.go': 'go',
};

export class ConverterPanel {
    static currentPanel: ConverterPanel | undefined;
    private readonly _panel: vscode.WebviewPanel;
    private readonly _port: number;
    private readonly _context: vscode.ExtensionContext;

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
        ConverterPanel.currentPanel = new ConverterPanel(panel, port, context);
    }

    private constructor(panel: vscode.WebviewPanel, port: number, context: vscode.ExtensionContext) {
        this._panel   = panel;
        this._port    = port;
        this._context = context;
        this._panel.webview.html = this._getHtml();
        this._panel.onDidDispose(() => { ConverterPanel.currentPanel = undefined; });

        this._panel.webview.onDidReceiveMessage(async (msg) => {
            switch (msg.type) {

                // ── Pick a single source/target file ──────────────────────────
                case 'pickFile': {
                    const uris = await vscode.window.showOpenDialog({
                        canSelectMany: false,
                        filters: {
                            'Source Files': ['py','js','ts','java','c','cpp','cc','cxx','rs','go'],
                            'All Files': ['*'],
                        },
                        openLabel: `Load ${msg.pane === 'src' ? 'Source' : 'Target'} File`,
                    });
                    if (uris?.length) {
                        const uri  = uris[0];
                        const text = Buffer.from(await vscode.workspace.fs.readFile(uri)).toString('utf8');
                        const ext  = uri.fsPath.replace(/.*(\.[^.]+)$/, '$1').toLowerCase();
                        const lang = EXT_TO_LANG[ext] || '';
                        const name = uri.fsPath.split(/[\\/]/).pop() ?? uri.fsPath;
                        this._panel.webview.postMessage({ type: 'fileLoaded', pane: msg.pane, text, lang, name });
                    }
                    break;
                }

                // ── Pick workspace folder (for WORKSPACE mode) ────────────────
                case 'pickFolder': {
                    const uris = await vscode.window.showOpenDialog({
                        canSelectFiles:   false,
                        canSelectFolders: true,
                        canSelectMany:    false,
                        openLabel:        'Select Codebase Folder',
                    });
                    if (uris?.length) {
                        const folderPath = uris[0].fsPath;
                        this._panel.webview.postMessage({ type: 'folderSelected', path: folderPath });
                    }
                    break;
                }

                // ── Read file by URI (VS Code explorer drag-drop) ─────────────
                case 'readFileUri': {
                    try {
                        const uri  = vscode.Uri.parse(msg.uri);
                        const text = Buffer.from(await vscode.workspace.fs.readFile(uri)).toString('utf8');
                        const ext  = uri.fsPath.replace(/.*(\.[^.]+)$/, '$1').toLowerCase();
                        const lang = EXT_TO_LANG[ext] || '';
                        const name = uri.fsPath.split(/[\\/]/).pop() ?? uri.fsPath;
                        this._panel.webview.postMessage({ type: 'fileLoaded', pane: msg.pane, text, lang, name });
                    } catch { /* ignore invalid URIs */ }
                    break;
                }

                // ── Open download URL in the system browser ───────────────────
                case 'openExternal': {
                    await vscode.env.openExternal(vscode.Uri.parse(msg.url));
                    break;
                }
            }
        });
    }

    private _getHtml(): string {
        const port = this._port;
        const langOpts = LANGUAGES.map(l => `<option value="${l}">${l}</option>`).join('');
        const langOptsAuto = `<option value="">Auto-detect</option>` + langOpts;

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
  --bg:#000;--bg2:#0e0e0e;--bg3:#141414;
  --border:rgba(255,255,255,0.09);--border-hi:rgba(255,255,255,0.22);
  --text:#e2e2e2;--muted:rgba(255,255,255,0.35);
  --accent:#8b8fc8;--accent-dim:rgba(139,143,200,0.15);
  --green:#4caf72;--err:#c45050;--grid:52px;
}
html,body{height:100%;overflow:hidden;background:var(--bg);color:var(--text);
  font-family:'Inter',system-ui,sans-serif;font-size:13px}

/* grid */
.grid{position:fixed;inset:0;pointer-events:none;z-index:0;
  background-image:linear-gradient(var(--border) 1px,transparent 1px),
                   linear-gradient(90deg,var(--border) 1px,transparent 1px);
  background-size:var(--grid) var(--grid)}
#wave-bg{position:fixed;inset:0;pointer-events:none;z-index:1;opacity:.05;width:100%;height:100%}

/* shell */
.shell{position:relative;z-index:2;display:flex;flex-direction:column;height:100vh}

/* ── header ── */
.hdr{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;
  padding:0 14px;height:46px;border-bottom:1px solid var(--border);
  background:rgba(0,0,0,.9);backdrop-filter:blur(6px);flex-shrink:0;gap:8px}
.hdr-brand{font-size:11px;font-weight:600;letter-spacing:.14em;text-transform:uppercase}

/* mode tabs */
.mode-tabs{display:flex;gap:0;border:1px solid var(--border)}
.mode-tab{background:transparent;color:var(--muted);border:none;border-right:1px solid var(--border);
  padding:5px 14px;font-family:inherit;font-size:9px;font-weight:700;
  letter-spacing:.14em;text-transform:uppercase;cursor:pointer;transition:all .15s}
.mode-tab:last-child{border-right:none}
.mode-tab:hover{color:var(--text)}
.mode-tab.active{background:var(--accent-dim);color:var(--accent)}

.hdr-right{display:flex;align-items:center;gap:8px}
.link-badge{display:none;align-items:center;gap:5px;font-size:9px;letter-spacing:.1em;
  text-transform:uppercase;color:var(--accent);border:1px solid var(--accent);
  padding:3px 8px}
.link-badge.show{display:flex}

/* ── shared select/btn styles ── */
select{appearance:none;-webkit-appearance:none;background:transparent;
  color:var(--text);border:1px solid var(--border);padding:4px 28px 4px 10px;
  font-family:inherit;font-size:11px;letter-spacing:.06em;text-transform:uppercase;
  cursor:pointer;outline:none;
  background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6' viewBox='0 0 10 6'%3E%3Cpath d='M0 0l5 6 5-6z' fill='rgba(255,255,255,0.4)'/%3E%3C/svg%3E");
  background-repeat:no-repeat;background-position:right 8px center}
select option{background:#1a1a1a}

.icon-btn{background:transparent;color:var(--muted);border:1px solid var(--border);
  padding:0 8px;height:24px;font-family:inherit;font-size:9px;letter-spacing:.1em;
  text-transform:uppercase;cursor:pointer;transition:all .15s;
  display:inline-flex;align-items:center;gap:4px;flex-shrink:0}
.icon-btn:hover{color:var(--text);border-color:var(--border-hi)}
.icon-btn.accent{color:var(--accent);border-color:rgba(139,143,200,.4)}
.icon-btn.accent:hover{background:var(--accent-dim)}
.icon-btn svg{width:11px;height:11px}
.icon-btn.big{height:30px;font-size:10px;padding:0 14px}

/* ── status strip (shared) ── */
.status-strip{border-top:1px solid var(--border);padding:5px 18px;
  font-size:10px;letter-spacing:.06em;color:var(--muted);
  background:rgba(0,0,0,.8);flex-shrink:0;min-height:24px;
  display:flex;align-items:center;gap:7px}
.sdot{width:5px;height:5px;border-radius:50%;background:var(--muted);flex-shrink:0}
.sdot.ok{background:var(--green)}.sdot.err{background:var(--err)}
.sdot.acc{background:var(--accent)}

/* ═════════════════════════════════════════════════
   MODE A — SINGLE FILE
   ═════════════════════════════════════════════════ */
#modeSingle{flex:1;display:flex;flex-direction:column;overflow:hidden}
.editors{flex:1;display:flex;overflow:hidden}
.pane{display:flex;flex-direction:column;flex:1;min-width:0;overflow:hidden;
  transition:outline .2s}
.pane+.pane{border-left:1px solid var(--border)}
.pane.has-file{outline:1px solid rgba(139,143,200,.3);outline-offset:-1px}
.pane-hdr{display:flex;align-items:center;padding:0 10px 0 14px;height:38px;
  border-bottom:1px solid var(--border);background:rgba(0,0,0,.6);
  flex-shrink:0;gap:7px}
.pane-label{font-size:9px;letter-spacing:.14em;text-transform:uppercase;color:var(--muted);flex-shrink:0}
.pane-file{font-size:9px;color:var(--accent);letter-spacing:.03em;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1;min-width:0}
.pane-actions{display:flex;align-items:center;gap:5px;flex-shrink:0}
.pane-wrap{position:relative;flex:1;display:flex;flex-direction:column;overflow:hidden}

.drop-zone{position:absolute;inset:0;z-index:50;display:none;align-items:center;
  justify-content:center;flex-direction:column;gap:7px;
  background:rgba(0,0,0,.88);border:2px dashed rgba(139,143,200,.5);
  font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:var(--accent);
  pointer-events:none}
.pane-wrap.dragging .drop-zone{display:flex}

.code-area{flex:1;width:100%;background:transparent;border:none;color:var(--text);
  font-family:'Consolas','SF Mono','Courier New',monospace;font-size:12.5px;
  padding:14px;resize:none;outline:none;line-height:1.6;
  scrollbar-width:thin;scrollbar-color:var(--border) transparent}
.code-area::-webkit-scrollbar{width:3px}
.code-area::-webkit-scrollbar-thumb{background:var(--border)}
.code-area::placeholder{color:var(--muted)}
.code-area[readonly]{cursor:default}

.toolbar-single{border-top:1px solid var(--border);display:flex;align-items:stretch;
  height:50px;flex-shrink:0;background:rgba(0,0,0,.92)}
#convertBtn{flex:1;background:#fff;color:#000;border:none;font-family:inherit;
  font-size:11px;font-weight:700;letter-spacing:.16em;text-transform:uppercase;
  cursor:pointer;transition:opacity .15s}
#convertBtn:hover{opacity:.85}
#convertBtn:disabled{opacity:.35;cursor:not-allowed}
.copy-btn{background:transparent;color:var(--muted);border:none;
  border-left:1px solid var(--border);padding:0 18px;font-family:inherit;
  font-size:9px;letter-spacing:.12em;text-transform:uppercase;cursor:pointer;
  transition:color .15s;flex-shrink:0}
.copy-btn:hover{color:var(--text)}

/* ═════════════════════════════════════════════════
   MODES B & C — WORKSPACE / ZIP (shared layout)
   ═════════════════════════════════════════════════ */
.mode-multi{flex:1;display:flex;flex-direction:column;overflow:hidden}

/* config section */
.config-panel{padding:18px 20px;border-bottom:1px solid var(--border);
  background:rgba(0,0,0,.6);flex-shrink:0}
.config-row{display:flex;align-items:center;gap:10px;margin-bottom:10px;flex-wrap:wrap}
.config-row:last-child{margin-bottom:0}
.cfg-label{font-size:9px;letter-spacing:.14em;text-transform:uppercase;
  color:var(--muted);min-width:120px;flex-shrink:0}
.cfg-path{flex:1;min-width:200px;background:transparent;border:1px solid var(--border);
  color:var(--text);padding:5px 10px;font-family:'Consolas','SF Mono',monospace;
  font-size:11px;outline:none;cursor:default;overflow:hidden;
  text-overflow:ellipsis;white-space:nowrap}
.cfg-path.filled{color:var(--accent);border-color:rgba(139,143,200,.4)}

/* zip drop zone */
.zip-drop{display:flex;align-items:center;justify-content:center;flex-direction:column;
  gap:8px;border:1.5px dashed var(--border);padding:20px;flex:1;min-width:240px;
  cursor:pointer;transition:border-color .2s,background .2s;
  font-size:10px;letter-spacing:.14em;text-transform:uppercase;color:var(--muted)}
.zip-drop:hover,.zip-drop.dragging{border-color:rgba(139,143,200,.5);
  background:var(--accent-dim);color:var(--accent)}
.zip-drop-icon{font-size:24px;margin-bottom:4px}
.zip-file-name{font-size:10px;color:var(--accent);letter-spacing:.04em;margin-top:4px;
  word-break:break-all;text-align:center}

/* action bar */
.action-bar{display:flex;align-items:center;gap:10px;margin-top:12px;flex-wrap:wrap}
.start-btn{background:#fff;color:#000;border:none;padding:0 28px;height:36px;
  font-family:inherit;font-size:11px;font-weight:700;letter-spacing:.16em;
  text-transform:uppercase;cursor:pointer;transition:opacity .15s;flex-shrink:0}
.start-btn:hover{opacity:.85}
.start-btn:disabled{opacity:.35;cursor:not-allowed}

/* progress area */
.progress-area{flex:1;display:flex;flex-direction:column;overflow:hidden;padding:18px 20px;gap:12px}
.prog-header{display:flex;align-items:center;justify-content:space-between;flex-shrink:0}
.prog-title{font-size:10px;font-weight:600;letter-spacing:.14em;text-transform:uppercase}
.prog-count{font-size:10px;color:var(--accent);letter-spacing:.06em}

.prog-bar-wrap{height:2px;background:var(--border);flex-shrink:0;border-radius:1px}
.prog-bar{height:2px;background:var(--accent);width:0;border-radius:1px;
  transition:width .4s ease}

.file-log{flex:1;overflow-y:auto;scrollbar-width:thin;scrollbar-color:var(--border) transparent}
.file-log::-webkit-scrollbar{width:3px}
.file-log::-webkit-scrollbar-thumb{background:var(--border)}
.log-entry{display:flex;align-items:center;gap:8px;padding:3px 0;
  font-size:11px;font-family:'Consolas','SF Mono',monospace;letter-spacing:.02em;
  border-bottom:1px solid rgba(255,255,255,.03)}
.log-entry:last-child{border-bottom:none}
.log-icon{width:14px;flex-shrink:0;text-align:center;font-size:11px}
.log-path{flex:1;color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.log-status{font-size:9px;letter-spacing:.1em;text-transform:uppercase;
  flex-shrink:0;min-width:70px;text-align:right}
.log-status.converting{color:var(--accent)}
.log-status.done{color:var(--green)}
.log-status.error{color:var(--err)}
.log-status.skipped{color:var(--muted)}

/* download banner */
.dl-banner{display:none;align-items:center;gap:12px;padding:12px 16px;
  background:rgba(139,143,200,.12);border:1px solid rgba(139,143,200,.3);flex-shrink:0}
.dl-banner.show{display:flex}
.dl-banner-text{font-size:11px;color:var(--accent);flex:1;letter-spacing:.04em}
.dl-btn{background:var(--accent);color:#000;border:none;padding:7px 20px;
  font-family:inherit;font-size:10px;font-weight:700;letter-spacing:.14em;
  text-transform:uppercase;cursor:pointer;transition:opacity .15s;flex-shrink:0}
.dl-btn:hover{opacity:.85}
.err-banner{display:none;align-items:center;gap:10px;padding:12px 16px;
  background:rgba(196,80,80,.1);border:1px solid rgba(196,80,80,.3);flex-shrink:0}
.err-banner.show{display:flex}
.err-banner-text{font-size:11px;color:var(--err)}
</style>
</head>
<body>
<div class="grid"></div>
<canvas id="wave-bg"></canvas>

<div class="shell">

<!-- ── Header ── -->
<div class="hdr">
  <span class="hdr-brand">CodeLens AI &nbsp;/&nbsp; Code Converter</span>
  <div class="mode-tabs">
    <button class="mode-tab active" id="tabSingle">Single File</button>
    <button class="mode-tab"        id="tabWorkspace">Workspace</button>
    <button class="mode-tab"        id="tabZip">ZIP</button>
  </div>
  <div class="hdr-right">
    <span class="link-badge" id="linkBadge">⬡ FILES LINKED</span>
  </div>
</div>

<!-- ═══════════════════════════════════════════
     MODE A — SINGLE FILE
     ═══════════════════════════════════════════ -->
<div id="modeSingle" class="mode-view" style="flex:1;display:flex;flex-direction:column;overflow:hidden">

  <div class="editors">
    <!-- Source pane -->
    <div class="pane" id="srcPane">
      <div class="pane-hdr">
        <span class="pane-label">Source</span>
        <span class="pane-file" id="srcFileName"></span>
        <div class="pane-actions">
          <select id="srcLang">${langOpts}</select>
          <label class="icon-btn accent" for="srcFileInput">
            <svg viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.3">
              <path d="M1.5 10.5h9M2.5 8.5V4a1 1 0 0 1 1-1H6l1.5 1.5H9a1 1 0 0 1 1 1v3"/>
              <path d="M6 2.5v4M4.5 5l1.5 1.5L7.5 5"/>
            </svg>FILE
          </label>
          <button class="icon-btn" id="srcClear">✕</button>
        </div>
      </div>
      <div class="pane-wrap" id="srcWrap">
        <div class="drop-zone">⬇ Drop file here</div>
        <textarea class="code-area" id="srcCode"
          placeholder="Paste code here, or click FILE to load a file&#10;You can also drag &amp; drop a source file onto this pane."></textarea>
      </div>
    </div>

    <!-- Output pane -->
    <div class="pane" id="tgtPane">
      <div class="pane-hdr">
        <span class="pane-label">Output</span>
        <span class="pane-file" id="tgtFileName"></span>
        <div class="pane-actions">
          <select id="tgtLang">${langOpts}</select>
          <label class="icon-btn accent" for="tgtFileInput">
            <svg viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.3">
              <path d="M1.5 10.5h9M2.5 8.5V4a1 1 0 0 1 1-1H6l1.5 1.5H9a1 1 0 0 1 1 1v3"/>
              <path d="M6 2.5v4M4.5 5l1.5 1.5L7.5 5"/>
            </svg>FILE
          </label>
          <button class="icon-btn" id="tgtClear">✕</button>
        </div>
      </div>
      <div class="pane-wrap" id="tgtWrap">
        <div class="drop-zone">⬇ Drop file here</div>
        <textarea class="code-area" id="tgtCode" readonly
          placeholder="Converted code appears here&#10;Load a target file to auto-set the output language."></textarea>
      </div>
    </div>
  </div>

  <div class="toolbar-single">
    <button id="convertBtn">&gt;&gt;&gt;&nbsp;&nbsp;CONVERT</button>
    <button class="copy-btn" id="copyBtn">COPY</button>
  </div>
</div>

<!-- ═══════════════════════════════════════════
     MODE B — WORKSPACE
     ═══════════════════════════════════════════ -->
<div id="modeWorkspace" class="mode-view" style="flex:1;display:none;flex-direction:column;overflow:hidden">

  <div class="config-panel">
    <div class="config-row">
      <span class="cfg-label">Folder</span>
      <input class="cfg-path" id="wsFolder" readonly placeholder="Click BROWSE to select a workspace folder…">
      <button class="icon-btn accent big" id="wsBrowse">BROWSE</button>
    </div>
    <div class="config-row">
      <span class="cfg-label">Source Language</span>
      <select id="wsSourceLang">${langOptsAuto}</select>
    </div>
    <div class="config-row">
      <span class="cfg-label">Target Language</span>
      <select id="wsTargetLang">${langOpts}</select>
    </div>
    <div class="action-bar">
      <button class="start-btn" id="wsStart" disabled>&gt;&gt;&gt; START CONVERSION</button>
      <span id="wsFileSummary" style="font-size:10px;color:var(--muted);letter-spacing:.06em"></span>
    </div>
  </div>

  <div class="progress-area" id="wsProgressArea">
    <div class="dl-banner"  id="wsDlBanner">
      <span class="dl-banner-text" id="wsDlText">✓ Conversion complete</span>
      <button class="dl-btn" id="wsDlBtn">⬇ DOWNLOAD ZIP</button>
    </div>
    <div class="err-banner" id="wsErrBanner">
      <span class="err-banner-text" id="wsErrText"></span>
    </div>
    <div class="prog-header">
      <span class="prog-title" id="wsProgTitle">Ready</span>
      <span class="prog-count" id="wsProgCount"></span>
    </div>
    <div class="prog-bar-wrap"><div class="prog-bar" id="wsProgBar"></div></div>
    <div class="file-log" id="wsFileLog"></div>
  </div>
</div>

<!-- ═══════════════════════════════════════════
     MODE C — ZIP
     ═══════════════════════════════════════════ -->
<div id="modeZip" class="mode-view" style="flex:1;display:none;flex-direction:column;overflow:hidden">

  <div class="config-panel">
    <div class="config-row" style="align-items:flex-start">
      <span class="cfg-label" style="padding-top:6px">ZIP File</span>
      <div class="zip-drop" id="zipDrop">
        <div class="zip-drop-icon">🗜</div>
        <div>Drop .zip here or <u style="cursor:pointer" id="zipBrowseLink">click to browse</u></div>
        <div class="zip-file-name" id="zipFileName"></div>
      </div>
      <input type="file" id="zipInput" accept=".zip" style="display:none">
    </div>
    <div class="config-row">
      <span class="cfg-label">Source Language</span>
      <select id="zipSourceLang">${langOptsAuto}</select>
    </div>
    <div class="config-row">
      <span class="cfg-label">Target Language</span>
      <select id="zipTargetLang">${langOpts}</select>
    </div>
    <div class="action-bar">
      <button class="start-btn" id="zipStart" disabled>&gt;&gt;&gt; TRANSLATE ZIP</button>
      <span id="zipFileSummary" style="font-size:10px;color:var(--muted);letter-spacing:.06em"></span>
    </div>
  </div>

  <div class="progress-area" id="zipProgressArea">
    <div class="dl-banner"  id="zipDlBanner">
      <span class="dl-banner-text" id="zipDlText">✓ Conversion complete</span>
      <button class="dl-btn" id="zipDlBtn">⬇ DOWNLOAD ZIP</button>
    </div>
    <div class="err-banner" id="zipErrBanner">
      <span class="err-banner-text" id="zipErrText"></span>
    </div>
    <div class="prog-header">
      <span class="prog-title" id="zipProgTitle">Ready</span>
      <span class="prog-count" id="zipProgCount"></span>
    </div>
    <div class="prog-bar-wrap"><div class="prog-bar" id="zipProgBar"></div></div>
    <div class="file-log" id="zipFileLog"></div>
  </div>
</div>

<!-- ── Status strip ── -->
<div class="status-strip">
  <div class="sdot" id="sDot"></div>
  <span id="sText">&nbsp;</span>
</div>

</div><!-- .shell -->

<script>
const vscode = acquireVsCodeApi();
const API    = 'http://localhost:${port}';

// ── Wave bg ───────────────────────────────────────────────────────────────────
(function(){
  const c   = document.getElementById('wave-bg');
  const ctx = c.getContext('2d');
  let t = 0;
  function resize(){ c.width=window.innerWidth; c.height=window.innerHeight; }
  resize();
  window.addEventListener('resize', resize);
  function frame(){
    ctx.clearRect(0,0,c.width,c.height);
    for(let w=0;w<8;w++){
      const by=c.height/9*(w+1), amp=18+w*4, freq=.012-w*.0005, ph=t*(.6+w*.12);
      ctx.beginPath(); ctx.strokeStyle='rgba(255,255,255,.9)'; ctx.lineWidth=.8;
      for(let x=0;x<=c.width;x+=2){
        const y=by+Math.sin(x*freq+ph)*amp+Math.sin(x*freq*1.7+ph*.8)*amp*.4;
        x?ctx.lineTo(x,y):ctx.moveTo(x,y);
      }
      ctx.stroke();
    }
    t+=.016;
    requestAnimationFrame(frame);
  }
  frame();
})();

// ── Status helper ─────────────────────────────────────────────────────────────
function setStatus(msg, type){
  document.getElementById('sText').textContent = msg || '\\u00a0';
  document.getElementById('sDot').className = 'sdot' + (type ? ' '+type : '');
}

// ═══════════════════════════════════════════════════════════════════
// MODE TABS
// ═══════════════════════════════════════════════════════════════════
const views = { single:'modeSingle', workspace:'modeWorkspace', zip:'modeZip' };
const tabs  = { single:'tabSingle',  workspace:'tabWorkspace',  zip:'tabZip'  };

function switchMode(mode){
  Object.entries(views).forEach(([k,id]) => {
    document.getElementById(id).style.display = (k===mode) ? 'flex' : 'none';
  });
  Object.entries(tabs).forEach(([k,id]) => {
    document.getElementById(id).classList.toggle('active', k===mode);
  });
  document.getElementById('linkBadge').className = 'link-badge' +
    (mode==='single' && _sf.srcFile && _sf.tgtFile ? ' show' : '');
}

document.getElementById('tabSingle').addEventListener('click',    ()=>switchMode('single'));
document.getElementById('tabWorkspace').addEventListener('click', ()=>switchMode('workspace'));
document.getElementById('tabZip').addEventListener('click',       ()=>switchMode('zip'));

// ═══════════════════════════════════════════════════════════════════
// MODE A — SINGLE FILE
// ═══════════════════════════════════════════════════════════════════
const _sf = { srcFile:null, tgtFile:null };

const sfSrcLang = document.getElementById('srcLang');
const sfTgtLang = document.getElementById('tgtLang');
const sfSrcCode = document.getElementById('srcCode');
const sfTgtCode = document.getElementById('tgtCode');
sfTgtLang.value = 'javascript';

const EXT_MAP = {'.py':'python','.js':'javascript','.ts':'typescript',
  '.java':'java','.c':'c','.cpp':'cpp','.cc':'cpp','.cxx':'cpp','.rs':'rust','.go':'go'};

function applyFile(pane, text, lang, name){
  if(pane==='src'){
    sfSrcCode.value = text;
    if(lang) sfSrcLang.value = lang;
    document.getElementById('srcFileName').textContent = name;
    _sf.srcFile = {name,lang};
    document.getElementById('srcPane').classList.add('has-file');
    setStatus('Source loaded: '+name+(lang?' ('+lang+')':''), 'acc');
  } else {
    if(lang) sfTgtLang.value = lang;
    document.getElementById('tgtFileName').textContent = name+' (lang set)';
    sfTgtCode.value = '';
    _sf.tgtFile = {name,lang};
    document.getElementById('tgtPane').classList.add('has-file');
    setStatus('Target language set from: '+name, 'acc');
  }
  document.getElementById('linkBadge').className =
    'link-badge' + (_sf.srcFile&&_sf.tgtFile?' show':'');
}

// File picker buttons — label opens picker but we intercept click to use VS Code dialog
// (FileReader is sandboxed in webviews; extension host reads the file instead)
document.querySelector('label[for="srcFileInput"]').addEventListener('click', e=>{
  e.preventDefault();
  vscode.postMessage({type:'pickFile', pane:'src'});
});
document.querySelector('label[for="tgtFileInput"]').addEventListener('click', e=>{
  e.preventDefault();
  vscode.postMessage({type:'pickFile', pane:'tgt'});
});

// Clear buttons
document.getElementById('srcClear').addEventListener('click', ()=>{
  sfSrcCode.value='';
  document.getElementById('srcFileName').textContent='';
  document.getElementById('srcPane').classList.remove('has-file');
  _sf.srcFile=null;
  document.getElementById('linkBadge').className='link-badge';
  setStatus('');
});
document.getElementById('tgtClear').addEventListener('click', ()=>{
  sfTgtCode.value='';
  document.getElementById('tgtFileName').textContent='';
  document.getElementById('tgtPane').classList.remove('has-file');
  _sf.tgtFile=null;
  document.getElementById('linkBadge').className='link-badge';
  setStatus('');
});

// Drag & drop
function setupDrop(pane, wrapId, textarea){
  const wrap = document.getElementById(wrapId);
  ['dragenter','dragover'].forEach(ev=>wrap.addEventListener(ev,e=>{
    e.preventDefault(); wrap.classList.add('dragging');
  }));
  wrap.addEventListener('dragleave',e=>{if(!wrap.contains(e.relatedTarget))wrap.classList.remove('dragging');});
  wrap.addEventListener('drop',()=>wrap.classList.remove('dragging'));
  wrap.addEventListener('drop', e=>{
    e.preventDefault();
    const file = e.dataTransfer?.files?.[0];
    if(file){
      const ext = file.name.replace(/.*(\\.\\w+)$/,'$1').toLowerCase();
      const lang = EXT_MAP[ext]||'';
      const reader = new FileReader();
      reader.onload = ev=>applyFile(pane, ev.target.result, lang, file.name);
      reader.readAsText(file);
      return;
    }
    // VS Code explorer drag — files come as URI list, not File objects
    const uriList = e.dataTransfer?.getData('text/uri-list');
    if(uriList){
      const uri = uriList.trim().split('\\n')[0].replace(/\\r/,'').trim();
      if(uri) vscode.postMessage({type:'readFileUri', uri, pane});
    }
  });
}
setupDrop('src','srcWrap',sfSrcCode);
setupDrop('tgt','tgtWrap',sfTgtCode);

// Convert
document.getElementById('convertBtn').addEventListener('click', async ()=>{
  const code = sfSrcCode.value.trim();
  if(!code){ setStatus('Paste source code or load a file first.','err'); return; }
  const btn = document.getElementById('convertBtn');
  btn.disabled=true; btn.textContent='Converting…';
  sfTgtCode.value=''; sfTgtCode.setAttribute('readonly','');
  setStatus('Running inference: '+sfSrcLang.value+' → '+sfTgtLang.value+'…','acc');
  try{
    const res  = await fetch(API+'/convert',{method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({code, source_lang:sfSrcLang.value, target_lang:sfTgtLang.value})});
    const data = await res.json();
    sfTgtCode.removeAttribute('readonly');
    sfTgtCode.value = data.converted_code ?? JSON.stringify(data,null,2);
    setStatus('Done — '+sfSrcLang.value+' → '+sfTgtLang.value, 'ok');
  } catch(e){
    setStatus('Error: cannot reach backend.','err');
  }
  btn.disabled=false; btn.textContent='>>> CONVERT';
});

document.getElementById('copyBtn').addEventListener('click', ()=>{
  if(!sfTgtCode.value) return;
  navigator.clipboard.writeText(sfTgtCode.value).then(()=>{
    setStatus('Copied to clipboard.','ok');
    setTimeout(()=>setStatus(''),2000);
  });
});

// Messages from extension host (file / folder selection results)
window.addEventListener('message', e=>{
  const msg = e.data;
  if(msg.type==='fileLoaded')   applyFile(msg.pane, msg.text, msg.lang, msg.name);
  if(msg.type==='folderSelected') applyWorkspaceFolder(msg.path);
});

// ═══════════════════════════════════════════════════════════════════
// SHARED — Progress tracker
// ═══════════════════════════════════════════════════════════════════
function makeProgressTracker(prefix){
  const progBar   = document.getElementById(prefix+'ProgBar');
  const progTitle = document.getElementById(prefix+'ProgTitle');
  const progCount = document.getElementById(prefix+'ProgCount');
  const fileLog   = document.getElementById(prefix+'FileLog');
  const dlBanner  = document.getElementById(prefix+'DlBanner');
  const dlText    = document.getElementById(prefix+'DlText');
  const dlBtn     = document.getElementById(prefix+'DlBtn');
  const errBanner = document.getElementById(prefix+'ErrBanner');
  const errText   = document.getElementById(prefix+'ErrText');

  let _pollTimer  = null;
  let _jobId      = null;

  const STATUS_ICON = {converting:'⟳', done:'✓', error:'✗', skipped:'–'};
  const STATUS_CLS  = {converting:'converting', done:'done', error:'error', skipped:'skipped'};

  function reset(){
    progBar.style.width='0';
    progTitle.textContent='Starting…';
    progCount.textContent='';
    fileLog.innerHTML='';
    dlBanner.className='dl-banner';
    errBanner.className='err-banner';
  }

  function appendLog(path, status){
    const entry = document.createElement('div');
    entry.className='log-entry';
    entry.id='log-'+path.replace(/[^a-zA-Z0-9]/g,'_');
    const icon   = STATUS_ICON[status]||'?';
    const cls    = STATUS_CLS[status]||'';
    const parts  = path.split('/');
    const name   = parts.pop();
    const dir    = parts.length ? parts.join('/')+' / ' : '';
    entry.innerHTML =
      '<span class="log-icon">'+icon+'</span>'+
      '<span class="log-path"><span style="opacity:.45">'+escHtml(dir)+'</span>'+escHtml(name)+'</span>'+
      '<span class="log-status '+cls+'">'+status+'</span>';
    fileLog.appendChild(entry);
    fileLog.scrollTop = fileLog.scrollHeight;
  }

  function updateEntry(path, newStatus){
    const el = document.getElementById('log-'+path.replace(/[^a-zA-Z0-9]/g,'_'));
    if(el){
      const icon = el.querySelector('.log-icon');
      const stat = el.querySelector('.log-status');
      if(icon) icon.textContent = STATUS_ICON[newStatus]||'?';
      if(stat){
        stat.textContent = newStatus;
        stat.className   = 'log-status '+(STATUS_CLS[newStatus]||'');
      }
    } else {
      appendLog(path, newStatus);
    }
  }

  function escHtml(s){
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  function startPolling(jobId){
    _jobId = jobId;
    if(_pollTimer) clearInterval(_pollTimer);
    _pollTimer = setInterval(async ()=>{
      try{
        const r = await fetch(API+'/convert/job/'+jobId);
        const d = await r.json();
        // update UI
        progTitle.textContent = d.status==='done' ? 'Complete' :
                                d.status==='error'? 'Error' :
                                'Converting codebase…';
        progCount.textContent = d.done+' / '+d.total+' files  ('+d.percent+'%)';
        progBar.style.width   = d.percent+'%';

        // append new log entries
        (d.log||[]).forEach(entry=>{
          if(entry.status==='converting') appendLog(entry.path, 'converting');
          else                            updateEntry(entry.path, entry.status);
        });

        setStatus(d.done+'/'+d.total+' files — '+d.percent+'%', 'acc');

        if(d.status==='done'){
          clearInterval(_pollTimer);
          const fileCount = d.total;
          dlText.textContent  = '✓ Converted '+fileCount+' files  — ready to download';
          dlBanner.className  = 'dl-banner show';
          setStatus('Conversion complete — '+fileCount+' files', 'ok');
        }
        if(d.status==='error'){
          clearInterval(_pollTimer);
          errText.textContent  = '✗ '+d.error;
          errBanner.className  = 'err-banner show';
          setStatus('Conversion failed', 'err');
        }
      } catch(e){
        setStatus('Polling error: '+e,'err');
      }
    }, 1200);
  }

  dlBtn.addEventListener('click', ()=>{
    if(!_jobId) return;
    const url = API+'/convert/job/'+_jobId+'/download';
    vscode.postMessage({type:'openExternal', url});
  });

  return { reset, startPolling };
}

// ═══════════════════════════════════════════════════════════════════
// MODE B — WORKSPACE
// ═══════════════════════════════════════════════════════════════════
const wsTracker = makeProgressTracker('ws');
let _wsPath = '';

function applyWorkspaceFolder(path){
  _wsPath = path;
  const el = document.getElementById('wsFolder');
  el.value = path;
  el.classList.add('filled');
  document.getElementById('wsStart').disabled = false;
  document.getElementById('wsFileSummary').textContent = '← pick source & target language, then start';
  setStatus('Folder selected: '+path.split(/[\\\\/]/).pop(), 'acc');
}

document.getElementById('wsBrowse').addEventListener('click', ()=>
  vscode.postMessage({type:'pickFolder'}));

document.getElementById('wsStart').addEventListener('click', async ()=>{
  if(!_wsPath){ setStatus('Select a folder first.','err'); return; }
  const tgt = document.getElementById('wsTargetLang').value;
  const src = document.getElementById('wsSourceLang').value || null;
  const btn = document.getElementById('wsStart');
  btn.disabled = true;
  wsTracker.reset();
  setStatus('Submitting codebase conversion job…','acc');
  try{
    const res  = await fetch(API+'/convert/codebase',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({repo_path:_wsPath, target_lang:tgt, source_lang:src}),
    });
    if(!res.ok){
      const err = await res.json();
      setStatus('Error: '+(err.detail||'unknown'),'err');
      btn.disabled=false;
      return;
    }
    const data = await res.json();
    wsTracker.startPolling(data.job_id);
    setStatus('Job started: '+data.job_id,'acc');
  } catch(e){
    setStatus('Error: '+e,'err');
    btn.disabled=false;
  }
});

// ═══════════════════════════════════════════════════════════════════
// MODE C — ZIP
// ═══════════════════════════════════════════════════════════════════
const zipTracker = makeProgressTracker('zip');
let _zipFile = null;

const zipDrop    = document.getElementById('zipDrop');
const zipInput   = document.getElementById('zipInput');
const zipFnEl    = document.getElementById('zipFileName');

document.getElementById('zipBrowseLink').addEventListener('click', ()=> zipInput.click());
zipInput.addEventListener('change', ()=>{ if(zipInput.files[0]) loadZipFile(zipInput.files[0]); });

function loadZipFile(file){
  if(!file.name.endsWith('.zip')){ setStatus('Only .zip files accepted.','err'); return; }
  _zipFile = file;
  zipFnEl.textContent   = file.name+' ('+formatBytes(file.size)+')';
  zipDrop.classList.add('has-file');
  document.getElementById('zipStart').disabled = false;
  document.getElementById('zipFileSummary').textContent = '← pick target language, then start';
  setStatus('ZIP loaded: '+file.name,'acc');
}

function formatBytes(b){
  if(b<1024)     return b+' B';
  if(b<1048576)  return (b/1024).toFixed(1)+' KB';
  return (b/1048576).toFixed(1)+' MB';
}

// Drag & drop on the ZIP zone
['dragenter','dragover'].forEach(ev=>zipDrop.addEventListener(ev,e=>{
  e.preventDefault(); zipDrop.classList.add('dragging');
}));
['dragleave','drop'].forEach(ev=>zipDrop.addEventListener(ev,()=>zipDrop.classList.remove('dragging')));
zipDrop.addEventListener('drop', e=>{
  e.preventDefault();
  const file = e.dataTransfer?.files?.[0];
  if(file) loadZipFile(file);
});

document.getElementById('zipStart').addEventListener('click', async ()=>{
  if(!_zipFile){ setStatus('Load a ZIP file first.','err'); return; }
  const tgt = document.getElementById('zipTargetLang').value;
  const src = document.getElementById('zipSourceLang').value || null;
  const btn = document.getElementById('zipStart');
  btn.disabled = true;
  zipTracker.reset();
  setStatus('Uploading ZIP and starting conversion…','acc');
  try{
    const form = new FormData();
    form.append('file', _zipFile);
    form.append('target_lang', tgt);
    if(src) form.append('source_lang', src);

    const res  = await fetch(API+'/convert/zip',{ method:'POST', body:form });
    if(!res.ok){
      const err = await res.json();
      setStatus('Error: '+(err.detail||'unknown'),'err');
      btn.disabled=false;
      return;
    }
    const data = await res.json();
    zipTracker.startPolling(data.job_id);
    setStatus('Job started: '+data.job_id,'acc');
  } catch(e){
    setStatus('Error: '+e,'err');
    btn.disabled=false;
  }
});
</script>
</body>
</html>`;
    }
}
