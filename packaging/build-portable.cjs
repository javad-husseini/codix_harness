// Execute with Node inside Docker. Only allowlisted product files enter the archive.
const fs = require('node:fs/promises');
const path = require('node:path');
const https = require('node:https');
const { execFileSync } = require('node:child_process');
const crypto = require('node:crypto');

async function download(url, hops = 0) {
  if (hops > 5) throw new Error('Too many download redirects');
  return new Promise((resolve, reject) => {
    const request = https.get(url, response => {
      if ([301, 302, 303, 307, 308].includes(response.statusCode)) {
        response.resume();
        const next = new URL(response.headers.location, url);
        if (next.protocol !== 'https:') return reject(new Error('Non-HTTPS download'));
        resolve(download(next.href, hops + 1));
      } else if (response.statusCode === 200) {
        const chunks = [];
        response.on('data', chunk => chunks.push(chunk));
        response.on('end', () => resolve(Buffer.concat(chunks)));
        response.on('error', reject);
      } else { response.resume(); reject(new Error(`Download HTTP ${response.statusCode}`)); }
    }).on('error', reject);
    request.setTimeout(180000, () => request.destroy(new Error('Download timed out')));
  });
}

(async () => {
  const root = path.resolve(__dirname, '..');
  const version = require('../package.json').devDependencies.electron;
  const filename = `electron-v${version}-win32-x64.zip`;
  const base = `https://github.com/electron/electron/releases/download/v${version}/`;
  const cache = path.join(root, 'runtime', 'downloads', filename);
  await fs.mkdir(path.dirname(cache), { recursive: true });
  let zip;
  try { zip = await fs.readFile(cache); }
  catch {
    console.log(`Downloading ${filename}`);
    execFileSync('curl', ['--fail', '--location', '--retry', '2', '--silent', '--show-error',
      '--connect-timeout', '20', '--max-time', '600', '--output', cache + '.part', base + filename], { stdio: 'inherit' });
    await fs.rename(cache + '.part', cache);
    zip = await fs.readFile(cache);
  }
  const checksums = (await download(base + 'SHASUMS256.txt')).toString();
  const expected = checksums.split('\n').map(line => line.trim().split(/\s+/))
    .find(parts => parts[1]?.replace(/^\*/, '') === filename)?.[0];
  if (!expected || crypto.createHash('sha256').update(zip).digest('hex') !== expected)
    throw new Error('Electron checksum verification failed');
  const destination = path.join(root, 'dist', process.argv.includes('--updated') ? 'Codix-win32-x64-updated' : 'Codix-win32-x64');
  await fs.mkdir(destination, { recursive: true });
  const archive = '/tmp/codix-electron-win.zip';
  await fs.writeFile(archive, zip);
  execFileSync('unzip', ['-q', '-o', archive, '-d', destination]);
  await fs.rename(path.join(destination, 'electron.exe'), path.join(destination, 'Codix.exe'));
  const app = path.join(destination, 'resources', 'app');
  await fs.mkdir(app, { recursive: true });
  for (const folder of ['desktop', 'out'])
    await fs.cp(path.join(root, folder), path.join(app, folder), { recursive: true });
  await fs.writeFile(path.join(app, 'package.json'), JSON.stringify({ name: 'codix', version: '0.1.0', main: 'desktop/main.cjs' }));
  await fs.cp(path.join(root, 'runtime', 'codix-backend'), path.join(destination, 'resources', 'backend'), { recursive: true });
  await fs.mkdir(path.join(destination, 'docker'), { recursive: true });
  await fs.copyFile(path.join(root, 'docker', 'default.Dockerfile'), path.join(destination, 'docker', 'default.Dockerfile'));
  await fs.copyFile('/opt/wine/drive_c/Python312/LICENSE.txt', path.join(destination, 'PYTHON-LICENSE.txt'));
  await fs.writeFile(path.join(destination, 'README.txt'), 'Run Codix.exe. Docker Desktop with the Linux engine and WSL2 are required.\r\nKeep this entire folder together. API key: %LOCALAPPDATA%\\Codix\\secrets\\avalai-key.dpapi\r\nModel: CODIX_MODEL environment variable.\r\nIf the default project image is absent, review docker/default.Dockerfile and approve/build it:\r\ndocker build -f docker/default.Dockerfile -t codix-project:node22-python312 .\r\n');
  console.log(`Portable folder: ${destination}`);
})().catch(error => { console.error(error.message); process.exitCode = 1; });
