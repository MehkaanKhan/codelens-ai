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
    const serverScript = path.join(workspaceRoot, 'backend', 'fastapi_server.py');

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

function registerChatParticipant(context: vscode.ExtensionContext, port: number) {
    const participant = vscode.chat.createChatParticipant(
        'codelens-ai',
        async (
            request: vscode.ChatRequest,
            _context: vscode.ChatContext,
            stream: vscode.ChatResponseStream,
            token: vscode.CancellationToken
        ) => {
            const query = request.prompt.trim();
            if (!query) {
                stream.markdown('Ask me anything about your indexed codebase.');
                return;
            }

            stream.progress('Searching codebase...');

            try {
                const res = await fetch(`http://localhost:${port}/chat`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ query, top_k: 5 }),
                    signal: token.isCancellationRequested ? AbortSignal.abort() : undefined,
                });

                if (!res.ok) {
                    stream.markdown('⚠️ Backend error. Make sure the CodeLens AI server is running.');
                    return;
                }

                const data = await res.json() as { answer: string; sources?: { file_path: string; start_line: number; end_line: number }[] };

                // Main answer
                stream.markdown(data.answer);

                // Source citations as clickable file links
                if (data.sources && data.sources.length > 0) {
                    stream.markdown('\n\n---\n**Sources:**');
                    const workspaceRoot = vscode.workspace.workspaceFolders?.[0]?.uri;
                    for (const src of data.sources) {
                        if (workspaceRoot) {
                            const fileUri = vscode.Uri.joinPath(workspaceRoot, src.file_path);
                            stream.anchor(
                                new vscode.Location(fileUri, new vscode.Range(
                                    Math.max(0, src.start_line - 1), 0,
                                    Math.max(0, src.end_line - 1), 0
                                )),
                                `${src.file_path} L${src.start_line}-${src.end_line}`
                            );
                        } else {
                            stream.markdown(`\n- \`${src.file_path}\` L${src.start_line}-${src.end_line}`);
                        }
                    }
                }

            } catch (e) {
                if (!token.isCancellationRequested) {
                    stream.markdown('⚠️ Cannot reach backend. Run **CodeLens AI: Start Server** or check that Python is installed.');
                }
            }
        }
    );

    participant.iconPath = new vscode.ThemeIcon('code');
    participant.followupProvider = {
        provideFollowups(_result, _context, _token) {
            return [
                { prompt: 'What are the main entry points?', label: 'Entry points', command: 'codelens-ai' },
                { prompt: 'What dependencies does this project use?', label: 'Dependencies', command: 'codelens-ai' },
                { prompt: 'Summarize the overall architecture.', label: 'Architecture', command: 'codelens-ai' },
            ];
        }
    };

    context.subscriptions.push(participant);
}

export function activate(context: vscode.ExtensionContext) {
    statusBarItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 0);
    statusBarItem.command = 'codelens-ai.openChat';
    context.subscriptions.push(statusBarItem);

    startServer(context);

    const { port } = getConfig();

    // Native VS Code Chat participant (@codelens-ai)
    registerChatParticipant(context, port);

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
