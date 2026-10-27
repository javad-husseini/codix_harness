// Real Electron renderer, authenticated API, native-approval bridge and real Linux PTYs in Docker.
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
require('../desktop/config.cjs').loadConfig = () => ({});
const childProcess = require('node:child_process');
const originalSpawn = childProcess.spawn;
childProcess.spawn = (executable, args, options) => originalSpawn(executable, ['-m', 'tests.desktop_workspace_backend'], options);
const { app, dialog } = require('electron');
const decisions = [];
const deadline = setTimeout(() => { console.error('Workspace panels smoke timed out'); app.exit(1); }, 60000);
dialog.showErrorBox = (_title, message) => { console.error(message); app.exit(1); };
dialog.showOpenDialog = async () => ({ canceled: false, filePaths: ['/fixture'] });
dialog.showMessageBox = async (_win, options) => {
  decisions.push(options);
  await new Promise(resolve => setTimeout(resolve, 100));
  return { response: options.detail.includes('touch DENIED') ? 1 : 0 };
};
app.on('browser-window-created', (_event, win) => {
  win.webContents.once('did-finish-load', async () => {
    const js = source => win.webContents.executeJavaScript(source);
    try {
      await js(`(async () => {
        const wait = async fn => { for (let i=0;i<150;i++) { if (fn()) return; await new Promise(r=>setTimeout(r,60)); } throw new Error('UI did not arrive'); };
        window.fixtureWait = wait;
        const button = text => [...document.querySelectorAll('button')].find(b=>b.textContent === text);
        await wait(()=>document.body.textContent.includes('Backend: متصل'));
        button('انتخاب پوشه').click();
        await wait(()=>button('آماده‌سازی محیط') && !button('آماده‌سازی محیط').disabled);
        button('آماده‌سازی محیط').click();
        await wait(()=>document.querySelector('button[title="hello.py"]'));
        document.querySelector('button[title="hello.py"]').click();
        await wait(()=>document.querySelector('.file-content')?.textContent.includes('سلام، Codix'));
        document.querySelector('button[title="src"]').click();
        await wait(()=>document.querySelector('button[title="src/second.py"]'));
        document.querySelector('button[title="src/second.py"]').click();
        await wait(()=>document.querySelector('.file-content')?.textContent.includes('answer = 42'));
        document.querySelector('.file-tabs button[title="hello.py"]').click();
        await wait(()=>document.querySelector('.file-content')?.textContent.includes('print('));
        if (document.querySelectorAll('.file-tab').length !== 2) throw new Error('Multiple file tabs missing');
        document.querySelector('[aria-label="بستن hello.py"]').click();
        await wait(()=>document.querySelector('.file-content')?.textContent.includes('answer = 42'));
        for (const [path, expected] of [['binary.dat','باینری'], ['large.txt','۳۲ کیبی‌بایت'], ['.env','Secret files']]) {
          document.querySelector('button[title="'+path+'"]').click();
          await wait(()=>document.querySelector('.file-viewer').textContent.includes(expected));
        }
        document.querySelector('.file-tabs button[title="src/second.py"]').click();
        await document.fonts.load('13px Vazirmatn', 'سلام');
        if (!document.fonts.check('13px Vazirmatn', 'سلام')) throw new Error('Offline local font missing');
        if (![...document.fonts].some(face => face.family.replaceAll('"','') === 'Vazirmatn' && face.status === 'loaded')) throw new Error('Vazirmatn was replaced by fallback');
        if (document.querySelector('.file-content').dir !== 'ltr') throw new Error('File is not LTR');
        if (document.querySelector('[contenteditable]')) throw new Error('Unexpected editor');
      })()`);
      const dimensions = () => js(`({explorer: document.querySelector('#explorer').getBoundingClientRect().width,
        chat: document.querySelector('#chat').getBoundingClientRect().width,
        terminals: document.querySelector('#terminals').getBoundingClientRect().height,
        overflow: document.documentElement.scrollWidth > innerWidth})`);
      const before = await dimensions();
      assert(Math.abs(before.explorer - 240) < 8, JSON.stringify(before));
      assert(Math.abs(before.chat - 360) < 8, JSON.stringify(before));
      assert(Math.abs(before.terminals - 240) < 8, JSON.stringify(before));
      assert.equal(before.overflow, false);
      win.webContents.debugger.attach('1.3');
      for (const [label, dx, dy, field] of [['تغییر عرض درخت فایل‌ها', 65, 0, 'explorer'], ['تغییر عرض چت و فایل‌ها', -60, 0, 'chat'], ['تغییر ارتفاع ترمینال', 0, -60, 'terminals']]) {
        const old = await dimensions();
        const rect = await js(`(() => { const r = document.querySelector('[aria-label="${label}"]').getBoundingClientRect(); return {x:r.x+r.width/2,y:r.y+r.height/2}; })()`);
        await win.webContents.debugger.sendCommand('Input.dispatchMouseEvent', { type:'mouseMoved', ...rect });
        await win.webContents.debugger.sendCommand('Input.dispatchMouseEvent', { type:'mousePressed', ...rect, button:'left', clickCount:1 });
        await win.webContents.debugger.sendCommand('Input.dispatchMouseEvent', { type:'mouseMoved', x:rect.x+dx,y:rect.y+dy, button:'left', buttons:1 });
        await win.webContents.debugger.sendCommand('Input.dispatchMouseEvent', { type:'mouseReleased', x:rect.x+dx,y:rect.y+dy, button:'left',clickCount:1 });
        await new Promise(resolve=>setTimeout(resolve,200));
        assert(Math.abs((await dimensions())[field] - old[field]) > 30, `Drag failed: ${field}`);
      }
      win.webContents.debugger.detach();
      const terminal = await js(`(async () => {
        const wait = window.fixtureWait;
        const call = async (name,...args) => { const r = await window.codix[name](...args); if(!r.ok) throw new Error(r.error); return r.data; };
        document.querySelector('[aria-label="ترمینال جدید"]').click();
        await wait(()=>document.querySelectorAll('.xterm').length === 1);
        const input = document.querySelector('.manual-terminal:not([hidden]) .terminal-input textarea');
        Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set.call(input,'printf "UI_REAL_OUTPUT\\n"');
        input.dispatchEvent(new Event('input',{bubbles:true}));
        await wait(()=>!input.form.querySelector('button').disabled);
        input.form.requestSubmit();
        await wait(()=>!input.disabled && input.value === '');
        // Identify the session through its normal bridge return, without exposing backend authentication.
        const second = await call('terminalOpen');
        await call('terminalInput',second.session_id,'cd src; export OWN=second; printf "SECOND_READY\\n"');
        const denied = await window.codix.terminalInput(second.session_id,'touch DENIED');
        if(denied.ok) throw new Error('Native rejection bypassed');
        const listing = await call('runTool','list_files',{path:'.'});
        if(listing.entries.some(e=>e.name==='DENIED')) throw new Error('Denied input executed');
        // Open a second visible tab through UI; both mounted xterm instances stay independent.
        document.querySelector('[aria-label="ترمینال جدید"]').click();
        await wait(()=>document.querySelectorAll('.xterm').length === 2);
        const tab = [...document.querySelectorAll('.terminal-tab button[role="tab"]')].find(b=>b.textContent==='Terminal 1');
        tab.click();
        await wait(()=>!document.querySelector('.manual-terminal').hidden);
        document.querySelector('[aria-label="بستن ترمینال 2"]').click();
        await wait(()=>document.querySelectorAll('.terminal-tab').length===1);
        await call('terminalInput',second.session_id,'printf "SIBLING_AFTER_CLOSE\\n"');
        let output='';
        for(let i=0;i<60;i++) {
          output=(await call('terminalPoll',second.session_id,0)).output;
          if(output.includes('SIBLING_AFTER_CLOSE\\r\\n')) break;
          await new Promise(r=>setTimeout(r,60));
        }
        if(!output.includes('SIBLING_AFTER_CLOSE\\r\\n')) throw new Error('Sibling did not survive close');
        await call('terminalClose',second.session_id);
        tab.click();
        return {output, terminals:document.querySelectorAll('.xterm').length};
      })()`);
      assert.equal(terminal.terminals, 1);
      assert(terminal.output.includes('SECOND_READY'));
      assert(decisions.every(d=>d.defaultId===1 && d.cancelId===1));
      if (process.env.CODIX_WORKSPACE_SCREENSHOT) await fs.writeFile(process.env.CODIX_WORKSPACE_SCREENSHOT,(await win.webContents.capturePage()).toPNG());
      win.setSize(900,700);
      await new Promise(resolve=>setTimeout(resolve,400));
      assert((await dimensions()).explorer < 2);
      assert.equal((await dimensions()).overflow,false);
      await js(`document.querySelector('[aria-label="نمایش یا جمع کردن درخت فایل‌ها"]').click()`);
      await new Promise(resolve=>setTimeout(resolve,200));
      assert((await dimensions()).explorer >= 180);
      // A project change closes the remaining UI terminal in the backend before resetting views.
      await js(`window.codix.selectProject()`);
      clearTimeout(deadline);
      console.log('PASS workspace: real readonly file tabs/binary/large/secret handling, all three mouse resize handles, responsive collapse, offline Vazirmatn, real PTY UI, native input denial, independent sessions and tab cleanup');
      app.quit();
    } catch (error) { console.error(error.stack); app.exit(1); }
  });
});
require('../desktop/main.cjs');
