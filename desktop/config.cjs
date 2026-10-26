// Configuration is read only in the main process, never loaded into process.env.
const fs = require('node:fs');
const { parseEnv } = require('node:util');
const ALLOWED = ['AVALAI_API_KEY', 'OPENAI_API_KEY', 'OPENAI_BASE_URL', 'CODIX_MODEL'];

function loadConfig(filename) {
  try {
    const info = fs.lstatSync(filename);
    if (!info.isFile() || info.isSymbolicLink() || info.nlink > 1 || info.size > 16384) throw new Error();
    const parsed = parseEnv(fs.readFileSync(filename, 'utf8'));
    return Object.fromEntries(ALLOWED.filter(key => Object.hasOwn(parsed, key)).map(key => [key, parsed[key]]));
  } catch (error) {
    if (error.code === 'ENOENT') return {};
    throw new Error('Cannot read .env configuration. Use a regular UTF-8 file smaller than 16 KB.');
  }
}

module.exports = { loadConfig };
