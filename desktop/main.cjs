// Capture/remove before app readiness or renderer creation; only the backend inherits the key.
const providerKey = process.env.OPENAI_API_KEY;
const avalaiKey = process.env.AVALAI_API_KEY;
delete process.env.OPENAI_API_KEY;
delete process.env.AVALAI_API_KEY;
const { app, BrowserWindow, dialog, ipcMain, protocol, net, session } = require('electron');
const { spawn } = require('node:child_process');
const { randomBytes, createHash } = require('node:crypto');
const path = require('node:path');
const fs = require('node:fs/promises');
const { loadConfig } = require('./config.cjs');
const { pathToFileURL } = require('node:url');

protocol.registerSchemesAsPrivileged([{ scheme: 'codix', privileges: { standard: true, secure: true, supportFetchAPI: true } }]);
const ROOT = path.resolve(__dirname, '..');
const token = randomBytes(32).toString('hex');
const rawPort = process.env.CODIX_API_PORT || '43121';
let backend;
let window;
let selection;
let project;
let busy = false;
let quitting = false;
let taskId;

async function request(endpoint, body) {
  const response = await fetch(`http://127.0.0.1:${rawPort}${endpoint}`, {
    method: body ? 'POST' : 'GET',
    headers: { Authorization: `Bearer ${token}`, ...(body ? { 'Content-Type': 'application/json' } : {}) },
    body: body ? JSON.stringify(body) : undefined,
    redirect: 'error', signal: AbortSignal.timeout(660000),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Backend operation failed.');
  return data;
}

async function startBackend() {
  if (!/^\d{1,5}$/.test(rawPort) || Number(rawPort) < 1024 || Number(rawPort) > 65535) {
    throw new Error('CODIX_API_PORT must be between 1024 and 65535.');
  }
  // Development launches happen in the development container. Packaged Windows mode uses bundled runtime only.
  const executable = app.isPackaged
    ? path.join(process.resourcesPath, 'backend', 'codix-backend.exe')
    : (process.platform === 'win32' ? path.join(ROOT, 'runtime', 'backend', 'codix-backend.exe') : 'python3');
  const args = !app.isPackaged && process.platform !== 'win32' ? ['-m', 'backend.server'] : [];
  const config = loadConfig(path.join(app.isPackaged ? path.dirname(process.execPath) : ROOT, '.env'));
  const env = { ...process.env, OPENAI_API_KEY: providerKey || '', AVALAI_API_KEY: avalaiKey || '',
    ...config, CODIX_API_PORT: rawPort };
  // Backend reads the provider key from its inherited environment; never pass it to renderer/project containers.
  backend = spawn(executable, args, { cwd: ROOT, env, stdio: ['pipe', 'pipe', 'pipe'], windowsHide: true });
  await new Promise((resolve, reject) => {
    let buffer = '';
    const timer = setTimeout(() => reject(new Error('Backend startup timed out.')), 15000);
    const fail = () => { clearTimeout(timer); reject(new Error('Backend could not start. Check bundled runtime and configured API port.')); };
    backend.once('error', fail);
    backend.once('exit', fail);
    backend.stdin.on('error', () => {});
    backend.stderr.on('data', () => {}); // Do not forward process output to logs or renderer.
    backend.stdout.on('data', chunk => {
      buffer = (buffer + chunk.toString()).slice(-1024);
      if (buffer.split(/\r?\n/).includes('CODIX_READY')) {
        clearTimeout(timer); resolve();
      }
    });
    backend.stdin.write(`${token}\n`);
  });
  backend.once('exit', () => {
    if (!quitting) { dialog.showErrorBox('Codix backend stopped', 'Restart the application. Current project files were preserved.'); app.quit(); }
  });
  await request('/health'); // Child readiness first: never trust an existing listener.
}

function trusted(event) {
  if (!window || event.sender !== window.webContents || event.senderFrame !== window.webContents.mainFrame
      || !event.senderFrame.url.startsWith('codix://app/')) {
    throw new Error('Untrusted IPC sender.');
  }
}

function handle(name, fn, argumentCount = 0) {
  ipcMain.handle(`codix:${name}`, async (event, ...args) => {
    trusted(event);
    if (args.length !== argumentCount || busy) return { ok: false, error: 'Invalid request or another operation is in progress.' };
    busy = true;
    try { return { ok: true, data: await fn(...args) }; }
    catch (error) { return { ok: false, error: error.message }; }
    finally { busy = false; }
  });
}

async function executeTool(name, args) {
  if (!project) throw new Error('Prepare the project container first.');
  const proposal = await request('/tools/propose', { project_id: project.project_id, name, arguments: args });
  let approved = false;
  if (proposal.approval_required) {
    const decision = await dialog.showMessageBox(window, {
      type: 'warning', title: 'Approve sensitive operation', buttons: ['Approve once', 'Reject'],
      defaultId: 1, cancelId: 1, message: proposal.reason, detail: proposal.detail,
    });
    approved = decision.response === 0;
  }
  // The renderer never receives the ticket and cannot supply an approval flag.
  return request('/tools/execute', { project_id: project.project_id, ticket: proposal.ticket, approved });
}

function registerBridge() {
  handle('health', () => request('/health'));
  handle('prerequisites', () => request('/prerequisites', {}));
  handle('select-project', async () => {
    const chosen = await dialog.showOpenDialog(window, { properties: ['openDirectory'] });
    if (chosen.canceled) return null;
    selection = null; project = null;
    selection = await request('/projects/preview', { root: chosen.filePaths[0] });
    return { root: selection.root, dockerfile: selection.dockerfile };
  });
  handle('prepare-project', async () => {
    if (!selection) throw new Error('Select a project first.');
    const current = selection;
    selection = null;
    let approved = false;
    if (current.dockerfile) {
      const choice = await dialog.showMessageBox(window, {
        type: 'warning', title: 'Approve project Dockerfile', defaultId: 1, cancelId: 1,
        buttons: ['Approve build and run', 'Reject'], message: current.reason,
        detail: `Project: ${current.root}\nDockerfile SHA256: ${current.dockerfile_sha256}\nBuild argv:\n${JSON.stringify(current.build_command)}\nRun argv:\n${JSON.stringify(current.container_command)}\nReview the project Dockerfile before approving.`,
      });
      approved = choice.response === 0;
    }
    project = await request('/projects/prepare', { ticket: current.ticket, approved });
    return project;
  });
  handle('smoke', () => {
    if (!project) throw new Error('Prepare the project container first.');
    return request('/projects/smoke', { project_id: project.project_id });
  });
  handle('set-plan', steps => {
    if (!Array.isArray(steps) || steps.length > 20) throw new Error('Invalid plan.');
    return executeTool('set_plan', { steps });
  }, 1);
  handle('run-tool', (name, args) => {
    if (!['list_files', 'read_file', 'create_file', 'edit_file', 'delete_file', 'run_command'].includes(name)
        || !args || typeof args !== 'object' || Array.isArray(args)
        || JSON.stringify(args).length > 220000) throw new Error('Invalid tool request.');
    return executeTool(name, args);
  }, 2);
  handle('start-task', async text => {
    if (!project || typeof text !== 'string' || text.length > 4000) throw new Error('Prepare a project and enter a task.');
    const result = await request('/tasks/start', { project_id: project.project_id, request: text });
    taskId = result.task_id;
    return result;
  }, 1);
  handle('task-status', async () => {
    if (!taskId) throw new Error('No task has started.');
    const result = await request('/tasks/status', { task_id: taskId });
    if (result.approval) {
      const { decision_id, reason, detail } = result.approval;
      const choice = await dialog.showMessageBox(window, {
        type: 'warning', title: 'Approve task operation', buttons: ['Approve once', 'Reject'],
        defaultId: 1, cancelId: 1, message: reason, detail,
      });
      await request('/tasks/decide', { task_id: taskId, decision_id, approved: choice.response === 0 });
      delete result.approval;
      result.status = 'running';
    }
    return result;
  });
}

async function main() {
  if (!app.requestSingleInstanceLock()) { app.quit(); return; }
  await app.whenReady();
  const output = path.join(ROOT, 'out');
  const index = await fs.readFile(path.join(output, 'index.html'), 'utf8');
  const inlineHashes = [...index.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi)]
    .filter(match => !/\bsrc\s*=/i.test(match[1]))
    .map(match => `'sha256-${createHash('sha256').update(match[2]).digest('base64')}'`).join(' ');
  protocol.handle('codix', async request => {
    const url = new URL(request.url);
    if (url.host !== 'app' || request.method !== 'GET') return new Response('', { status: 403 });
    const relative = decodeURIComponent(url.pathname === '/' ? '/index.html' : url.pathname);
    const target = path.resolve(output, `.${relative}`);
    if (!target.startsWith(output + path.sep)) return new Response('', { status: 403 });
    try {
      const resolved = await fs.realpath(target);
      if (!resolved.startsWith(output + path.sep)) return new Response('', { status: 403 });
      return net.fetch(pathToFileURL(resolved).href);
    } catch { return new Response('', { status: 404 }); }
  });
  session.defaultSession.webRequest.onHeadersReceived((details, done) => done({ responseHeaders: {
    ...details.responseHeaders,
    'Content-Security-Policy': [`default-src 'self'; script-src 'self' ${inlineHashes}; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-src 'none'; base-uri 'none'`],
  } }));
  await startBackend();
  registerBridge();
  window = new BrowserWindow({ width: 1040, height: 740, title: 'Codix', webPreferences: {
    preload: path.join(__dirname, 'preload.cjs'), contextIsolation: true, nodeIntegration: false, sandbox: true,
  } });
  window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  window.webContents.on('will-navigate', event => event.preventDefault());
  window.webContents.session.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
  await window.loadURL('codix://app/');
}

app.on('window-all-closed', () => app.quit());
app.on('before-quit', event => {
  if (backend && backend.exitCode === null && backend.pid) {
    event.preventDefault();
    if (quitting) return;
    quitting = true;
    const child = backend;
    child.stdin.end();
    const timer = setTimeout(() => child.kill(), 3000);
    child.once('exit', () => { clearTimeout(timer); app.quit(); });
  } else quitting = true;
});
main().catch(() => {
  dialog.showErrorBox('Codix startup failed', 'Check .env format, backend runtime, API port and UI build. See the setup documentation.');
  app.quit();
});
