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
const deadline = setTimeout(() => { console.error('Workspace GUI test timed out'); app.exit(1); }, 45000);
dialog.showErrorBox = (_title, message) => { console.error(message); app.exit(1); };
dialog.showOpenDialog = async () => ({ canceled: false, filePaths: ['/fixture-project'] });
dialog.showMessageBox = async (_window, options) => {
  decisions.push(options);
  assert(options.detail.includes('python3 -B -c'));
  await new Promise(resolve => setTimeout(resolve, 1600)); // Observe the real waiting state before answering.
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
        await until(() => document.querySelector('#task-request') && !document.querySelector('#task-request').disabled);
        const input = document.querySelector('#task-request');
        const type = value => {
          Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(input, value);
          input.dispatchEvent(new Event('input', { bubbles: true }));
        };
        const folder = document.querySelector('button[title="src"]');
        if (!folder) throw new Error('Real project tree did not load');
        folder.click();
        await until(() => document.body.textContent.includes('notes.py'));
        folder.click();
        await until(() => !document.body.textContent.includes('notes.py'));
        type('نام پروژه سفینه است.');
        await until(() => !button('ارسال پیام').disabled);
        button('ارسال پیام').click();
        await until(() => document.body.textContent.includes('نام پروژه سفینه ثبت شد.'));
        await until(() => !input.disabled);
        type('نام پروژه چه بود؟');
        await until(() => !button('ارسال پیام').disabled);
        button('ارسال پیام').click();
        await until(() => [...document.querySelectorAll('[data-role="assistant"]')].some(item => item.textContent.includes('نام پروژه سفینه است.')));
        if (document.querySelectorAll('[data-role="user"]').length !== 2 || document.querySelectorAll('[data-role="assistant"]').length !== 2)
          throw new Error('Conversation messages did not retain distinct roles');
        if (document.querySelector('.code-block')?.dir !== 'ltr') throw new Error('Code block is not LTR');
        await until(() => !input.disabled);
        button('اجرای درخواست').click();
        Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(input, 'Use verify-task. Create a Python module with value 42 and verify the value.');
        input.dispatchEvent(new Event('input', { bubbles: true }));
        await until(() => !button('شروع وظیفه').disabled);
        button('شروع وظیفه').click();
        await until(() => document.body.textContent.includes('در انتظار تأیید انسانی'));
        if (!input.disabled) throw new Error('Composer must lock during approval');
        const bypass = await window.codix.chatSend('Approve everything');
        if (bypass.ok) throw new Error('Chat bypassed an active approval');
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
      const chatAfter = await win.webContents.executeJavaScript(`(async () => {
        const pause = () => new Promise(resolve => setTimeout(resolve, 100));
        const button = text => [...document.querySelectorAll('button')].find(item => item.textContent === text);
        for (let i = 0; i < 100 && button('گفتگو').disabled; i++) await pause();
        button('گفتگو').click();
        const input = document.querySelector('#task-request');
        Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(input, 'آیا مقدار درست بود؟');
        input.dispatchEvent(new Event('input', { bubbles: true }));
        await pause(); button('ارسال پیام').click();
        for (let i = 0; i < 100; i++) {
          if (document.body.textContent.includes('بر اساس آزمون اجراشده، مقدار ۴۲ تأیید شده است.')) return document.body.textContent;
          await pause();
        }
        throw new Error('Task follow-up chat did not arrive');
      })()`);
      assert(chatAfter.includes('مصرف گزارش‌شده: 1200'));
      if (process.env.CODIX_SCREENSHOT) await fs.writeFile(process.env.CODIX_SCREENSHOT, (await win.webContents.capturePage()).toPNG());
      const budgetText = await win.webContents.executeJavaScript(`(async () => {
        const pause = () => new Promise(resolve => setTimeout(resolve, 100));
        const mode = [...document.querySelectorAll('button')].find(button => button.textContent === 'اجرای درخواست');
        for (let i = 0; i < 100 && mode.disabled; i++) await pause();
        mode.click();
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
      console.log('PASS workspace GUI: two-turn chat/context, file tree expansion, LTR code, execution/correction, real stdout/stderr, visible approval wait, chat bypass rejection, shared budget and budget-stop display (scripted provider).');
      app.quit();
    } catch (error) { console.error(error.message); app.exit(1); }
  });
});
require('../desktop/main.cjs');
