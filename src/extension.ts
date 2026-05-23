import * as vscode from 'vscode';
import * as cp from 'child_process';
import * as path from 'path';
import { ChatPanel } from './panels/ChatPanel';
import { ConverterPanel } from './panels/ConverterPanel';
import { GraphPanel } from './panels/GraphPanel';

let serverProcess: cp.ChildProcess | undefined;
let statusBarItem: vscode.StatusBarItem;

function getConfig() {
    const cfg = vscode.workspace.getConfiguration('codelens-ai');
    return {
        python: cfg.get<string>('pythonPath', 'python'),
        port: cfg.get<number>('backendPort', 8080),
    };
}

async function waitForServer(port: number, retries = 30, delayMs = 1000): Promise<boolean> {
    for (let i = 0; i < retries; i++) {
        try {
            const res = await fetch(`http://localhost:${port}/health`);
            if (res.ok) return true;
        } catch { /* server not up yet */ }
        await new Promise(r => setTimeout(r, delayMs));
    }
    return false;
}

async function startServer(context: vscode.ExtensionContext): Promise<void> {
    const workspaceRoot = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
    if (!workspaceRoot) return;

    const { python, port } = getConfig();
    const serverScript = path.join(workspaceRoot, 'tools', 'fastapi_server.py');

    statusBarItem.text = '$(sync~spin) CodeLens AI: Starting...';
    statusBarItem.tooltip = 'CodeLens AI backend is starting';
    statusBarItem.show();

    serverProcess = cp.spawn(python, [serverScript], {
        cwd: workspaceRoot,
        env: { ...process.env },
        shell: true,
    });

    serverProcess.stderr?.on('data', (data: Buffer) => {
        console.error('[CodeLens AI server]', data.toString());
    });

    serverProcess.on('error', (err) => {
        vscode.window.showErrorMessage(`CodeLens AI: Could not start backend — ${err.message}`);
        statusBarItem.text = '$(error) CodeLens AI: Error';
    });

    serverProcess.on('exit', (code) => {
        if (code !== 0 && code !== null) {
            statusBarItem.text = '$(error) CodeLens AI: Stopped';
        }
    });

    const ready = await waitForServer(port);
    if (ready) {
        statusBarItem.text = '$(check) CodeLens AI: Ready';
        statusBarItem.tooltip = `Backend running on localhost:${port}`;
    } else {
        statusBarItem.text = '$(warning) CodeLens AI: Not responding';
        vscode.window.showWarningMessage('CodeLens AI: Backend did not start in time. Check that Python and dependencies are installed.');
    }
}

async function indexWorkspace(port: number): Promise<void> {
    const workspaceRoot = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
    if (!workspaceRoot) {
        vscode.window.showErrorMessage('CodeLens AI: No workspace folder open.');
        return;
    }

    await vscode.window.withProgress(
        {
            location: vscode.ProgressLocation.Notification,
            title: 'CodeLens AI: Indexing repository...',
            cancellable: false,
        },
        async () => {
            try {
                const res = await fetch(`http://localhost:${port}/index`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ repo_path: workspaceRoot }),
                });
                if (res.ok) {
                    vscode.window.showInformationMessage('CodeLens AI: Repository indexed successfully.');
                } else {
                    const err = await res.json() as { detail?: string };
                    vscode.window.showErrorMessage(`CodeLens AI: Indexing failed — ${err.detail ?? 'unknown error'}`);
                }
            } catch (e) {
                vscode.window.showErrorMessage(`CodeLens AI: Indexing failed — ${e}`);
            }
        }
    );
}

export function activate(context: vscode.ExtensionContext) {
    statusBarItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 0);
    statusBarItem.command = 'codelens-ai.openChat';
    context.subscriptions.push(statusBarItem);

    startServer(context);

    const { port } = getConfig();

    context.subscriptions.push(
        vscode.commands.registerCommand('codelens-ai.openChat', () => {
            ChatPanel.createOrShow(context, port);
        }),
        vscode.commands.registerCommand('codelens-ai.openConverter', () => {
            ConverterPanel.createOrShow(context, port);
        }),
        vscode.commands.registerCommand('codelens-ai.openGraph', () => {
            GraphPanel.createOrShow(context, port);
        }),
        vscode.commands.registerCommand('codelens-ai.indexRepo', () => {
            indexWorkspace(port);
        }),
    );
}

export function deactivate() {
    if (serverProcess) {
        serverProcess.kill();
        serverProcess = undefined;
    }
}
