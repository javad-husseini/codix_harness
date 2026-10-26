// Run inside the GUI development container: xvfb-run -a node_modules/.bin/electron tests/desktop-smoke.cjs
const assert = require('node:assert/strict');
const { app, dialog } = require('electron');

const deadline = setTimeout(() => { console.error('Desktop smoke timed out'); app.exit(1); }, 20000);
dialog.showErrorBox = (_title, message) => { console.error(message); app.exit(1); };
dialog.showOpenDialog = async () => ({ canceled: true, filePaths: [] });
app.on('browser-window-created', (_event, win) => {
  win.webContents.once('did-finish-load', async () => {
    try {
      const state = await win.webContents.executeJavaScript(`(async () => ({
        title: document.title,
        heading: document.querySelector('h1')?.textContent,
        methods: Object.keys(window.codix),
        nodeAccess: typeof window.require,
        processAccess: typeof window.process,
        health: await window.codix.health(),
        prerequisites: await window.codix.prerequisites(),
        cancelledSelection: await window.codix.selectProject(),
        unprepared: await window.codix.prepareProject(),
        invalidTool: await window.codix.runTool('host_shell', {}),
        unplannedTool: await window.codix.runTool('create_file', { path: 'new.txt', content: 'x' }),
      }))()`);
      assert.equal(state.title, 'Codix');
      assert.equal(state.heading, 'Codix');
      assert.deepEqual(state.methods.sort(), ['health', 'prerequisites', 'prepareProject', 'selectProject', 'smoke', 'setPlan', 'runTool', 'startTask', 'taskStatus'].sort());
      assert.equal(state.nodeAccess, 'undefined');
      assert.equal(state.processAccess, 'undefined');
      assert.equal(state.health.ok, true);
      assert.equal(state.health.data.status, 'ready');
      // The dev container intentionally has no Docker socket or CLI. Missing prerequisites must be reported.
      assert.equal(state.prerequisites.ok, false);
      assert.match(state.prerequisites.error, /Docker|executable/i);
      assert.deepEqual(state.cancelledSelection, { ok: true, data: null });
      assert.equal(state.unprepared.ok, false);
      assert.match(state.unprepared.error, /Select a project/i);
      assert.equal(state.invalidTool.ok, false);
      assert.equal(state.unplannedTool.ok, false);
      assert.equal(win.webContents.getLastWebPreferences().sandbox, true);
      clearTimeout(deadline);
      console.log('PASS desktop: render, restricted bridge, authenticated backend, missing-Docker detection, cancelled selection, unprepared rejection, renderer sandbox');
      app.quit();
    } catch (error) {
      console.error(error.message);
      app.exit(1);
    }
  });
});
require('../desktop/main.cjs');
