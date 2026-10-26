const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { test } = require('node:test');
const { loadConfig } = require('../desktop/config.cjs');

test('dotenv allows only provider settings, preserves literal secrets and leaves process environment untouched', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'codix-env-'));
  const file = path.join(dir, '.env');
  const before = { ...process.env };
  try {
    fs.writeFileSync(file, '# fixture only\r\nAVALAI_API_KEY="fixture-$literal#key"\r\nOPENAI_API_KEY=\r\nCODIX_MODEL=gpt-test\r\nOPENAI_BASE_URL=https://api.avalai.ir/v1\r\nNODE_OPTIONS=--require=evil\r\nPATH=evil\r\nCODIX_API_PORT=1\r\n');
    assert.deepEqual(loadConfig(file), { AVALAI_API_KEY: 'fixture-$literal#key', OPENAI_API_KEY: '',
      OPENAI_BASE_URL: 'https://api.avalai.ir/v1', CODIX_MODEL: 'gpt-test' });
    assert.deepEqual({ ...process.env }, before);
    assert.deepEqual(loadConfig(path.join(dir, 'missing')), {});
  } finally { fs.rmSync(dir, { recursive: true, force: true }); }
});

test('rejects oversized, linked and nonregular configurations with fixed diagnostics', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'codix-env-'));
  const file = path.join(dir, '.env');
  const expected = /^Error: Cannot read .env configuration\./;
  try {
    fs.writeFileSync(file, 'fixture-private-value'.repeat(1000));
    assert.throws(() => loadConfig(file), expected);
    fs.writeFileSync(file, 'AVALAI_API_KEY=fixture-secret');
    fs.symlinkSync(file, path.join(dir, 'linked'));
    assert.throws(() => loadConfig(path.join(dir, 'linked')), expected);
    fs.linkSync(file, path.join(dir, 'hardlinked'));
    assert.throws(() => loadConfig(file), expected);
    assert.throws(() => loadConfig(dir), expected);
  } finally { fs.rmSync(dir, { recursive: true, force: true }); }
});
