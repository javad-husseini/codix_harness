// Test-only child launch substitution: production has no fixture-mode configuration.
const assert = require('node:assert/strict');
const childProcess = require('node:child_process');
const originalSpawn = childProcess.spawn;
childProcess.spawn = (executable, args, options) => {
  assert.equal(executable, 'python3');
  assert.deepEqual(args, ['-m', 'backend.server']);
  return originalSpawn(executable, ['-m', 'tests.desktop_backend'], options);
};
const { app, dialog } = require('electron');
const decisions = [];
const deadline = setTimeout(() => { console.error('Approval smoke timed out'); app.exit(1); }, 20000);
dialog.showErrorBox = (_title, message) => { console.error(message); app.exit(1); };
dialog.showOpenDialog = async () => ({ canceled: false, filePaths: ['/fixture-project'] });
dialog.showMessageBox = async (_window, options) => {
  decisions.push(options);
  return { response: /Delete a file|Every terminal command/.test(options.message) ? 1 : 0 };
};
app.on('browser-window-created', (_event, win) => {
  win.webContents.once('did-finish-load', async () => {
    try {
      const result = await win.webContents.executeJavaScript(`(async () => {
        const call = async (method, ...args) => {
          const result = await window.codix[method](...args);
          if (!result.ok) throw new Error(result.error);
          return result.data;
        };
        await call('selectProject');
        await call('prepareProject');
        await call('setPlan', ['Update instruction and request deletion']);
        await call('runTool', 'edit_file', { path: 'AGENTS.md', content: 'approved instruction\\n' });
        const instruction = await call('runTool', 'read_file', { path: 'AGENTS.md' });
        const deniedDelete = await window.codix.runTool('delete_file', { path: 'note.txt' });
        const note = await call('runTool', 'read_file', { path: 'note.txt' });
        const stoppedEdit = await window.codix.runTool('edit_file', { path: 'note.txt', content: 'not permitted' });
        await call('setPlan', ['Request a check']);
        const deniedCommand = await window.codix.runTool('run_command', { command: 'printf SHOULD_NOT_RUN', cwd: '.' });
        const listing = await call('runTool', 'list_files', { path: '.' });
        return { instruction, note, deniedDelete, stoppedEdit, deniedCommand, listing };
      })()`);
      assert.equal(result.instruction.content, 'approved instruction\n');
      assert.equal(result.note.content, 'keep this file\n');
      assert.equal(result.deniedDelete.ok, false);
      assert.equal(result.stoppedEdit.ok, false);
      assert.equal(result.deniedCommand.ok, false);
      assert(!result.listing.entries.some(entry => entry.name === 'UNEXPECTED_COMMAND'));
      assert.equal(decisions.length, 4);
      assert(decisions.every(item => item.defaultId === 1 && item.cancelId === 1));
      assert(decisions[0].detail.includes('+approved instruction'));
      assert(decisions[3].detail.includes('printf SHOULD_NOT_RUN'));
      clearTimeout(deadline);
      console.log('PASS approval GUI/API: protected diff approval, denied delete preserves file, task stops, revised-plan approval, denied command never executes');
      app.quit();
    } catch (error) {
      console.error(error.message);
      app.exit(1);
    }
  });
});
require('../desktop/main.cjs');
