const assert = require('node:assert/strict');
process.env.OPENAI_API_KEY = 'fixture-env-must-not-win';
process.env.AVALAI_API_KEY = 'fixture-env-must-not-win';
// Test the file-config handoff without opening a user's real .env.
require('../desktop/config.cjs').loadConfig = () => ({
  OPENAI_API_KEY: 'fixture-not-real-key', AVALAI_API_KEY: 'fixture-avalai-not-real-key',
});
const fs = require('node:fs/promises');
const childProcess = require('node:child_process');
const originalSpawn = childProcess.spawn;
childProcess.spawn = (executable, args, options) => {
  assert.equal(executable, 'python3');
  assert.deepEqual(args, ['-m', 'backend.server']);
  return originalSpawn(executable, ['-m', 'tests.desktop_task_backend'], options);
};
const { app, dialog } = require('electron');
const decisions = [];
const deadline = setTimeout(() => { console.error('Task GUI test timed out'); app.exit(1); }, 30000);
dialog.showErrorBox = (_title, message) => { console.error(message); app.exit(1); };
dialog.showOpenDialog = async () => ({ canceled: false, filePaths: ['/fixture-project'] });
dialog.showMessageBox = async (_window, options) => {
  decisions.push(options);
  assert(options.detail.includes('python3 -B -c'));
  return { response: 0 };
};
app.on('browser-window-created', (_event, win) => {
  win.webContents.once('did-finish-load', async () => {
    try {
      const result = await win.webContents.executeJavaScript(`(async () => {
        const pause = () => new Promise(resolve => setTimeout(resolve, 100));
        const until = async predicate => {
          for (let i = 0; i < 150; i++) { if (predicate()) return; await pause(); }
          throw new Error('UI state did not arrive');
        };
        await until(() => document.body.textContent.includes('Backend: متصل'));
        const button = text => [...document.querySelectorAll('button')].find(item => item.textContent === text);
        button('انتخاب پوشه').click();
        await until(() => button('آماده‌سازی محیط') && !button('آماده‌سازی محیط').disabled);
        button('آماده‌سازی محیط').click();
        await until(() => document.querySelector('#task-request'));
        const input = document.querySelector('#task-request');
        Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(input, 'Use verify-task. Create a Python module with value 42 and verify the value.');
        input.dispatchEvent(new Event('input', { bubbles: true }));
        await until(() => !button('شروع وظیفه').disabled);
        button('شروع وظیفه').click();
        await until(() => document.body.textContent.includes('Requested value verified.'));
        return { text: document.body.textContent, stages: [...document.querySelectorAll('ol li')].map(item => item.textContent),
                 exposed: Object.keys(window.codix), alerts: [...document.querySelectorAll('[role="alert"]')].map(item => item.textContent) };
      })()`);
      assert(result.text.includes('created.py'));
      assert(result.text.includes('Exit: 0'));
      assert.equal(result.stages.length, 2);
      assert(result.stages.every(text => text.includes('انجام شد')));
      assert.equal(result.alerts.length, 0);
      assert.equal(decisions.length, 2);
      assert(result.text.includes('verify-task'));
      assert(result.text.includes('Correction cycle 1/3'));
      assert(result.text.includes('Exit: 1'));
      assert.equal(decisions[0].defaultId, 1);
      assert(!result.text.includes('decision_id'));
      const rendererEnv = await fs.readFile(`/proc/${win.webContents.getOSProcessId()}/environ`, 'utf8');
      assert(!rendererEnv.includes('OPENAI_API_KEY='), 'Provider key must not be inherited by the renderer');
      assert(!rendererEnv.includes('AVALAI_API_KEY='), 'AvalAI key must not be inherited by the renderer');
      const budgetText = await win.webContents.executeJavaScript(`(async () => {
        const pause = () => new Promise(resolve => setTimeout(resolve, 100));
        const input = document.querySelector('#task-request');
        Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(input, 'Check budget reporting');
        input.dispatchEvent(new Event('input', { bubbles: true }));
        await pause();
        [...document.querySelectorAll('button')].find(button => button.textContent === 'شروع وظیفه').click();
        for (let i = 0; i < 100; i++) {
          if (document.body.textContent.includes('بودجه برای درخواست بعدی کافی نیست')) return document.body.textContent;
          await pause();
        }
        throw new Error('Budget stop was not shown');
      })()`);
      assert(budgetText.includes('12048'));
      assert(budgetText.includes('4960'));
      assert(budgetText.includes('مصرف گزارش‌شده: 20040'));
      assert(budgetText.includes('رزرو بدون گزارش مصرف: 0'));
      clearTimeout(deadline);
      console.log('PASS task GUI: correction/Skills/approval isolation, then accurate budget stop with reported usage, required next-call reserve and remaining balance (scripted provider)');
      app.quit();
    } catch (error) { console.error(error.message); app.exit(1); }
  });
});
require('../desktop/main.cjs');
