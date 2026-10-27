'use client';

import { useEffect, useRef, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Icon } from './icon';
import { FileTree } from './file-tree';
import { MessageContent } from './message-content';
import { TerminalPanel } from './terminal-panel';
import { FileViewer } from './file-viewer';
import { ResizablePanelGroup, ResizablePanel, ResizableHandle } from '@/components/ui/resizable';

const ACTIVE = ['running', 'awaiting_approval'];
const STATUS = { running: 'در حال اجرا', awaiting_approval: 'در انتظار تأیید', completed: 'انجام شد',
  incomplete: 'اعتبارسنجی ناقص', stopped: 'متوقف شد', failed: 'بررسی ناموفق', budget_exhausted: 'بودجه برای درخواست بعدی کافی نیست' };

function TaskDetails({ task }) {
  if (!task?.has_task) return null;
  return <details className="task-details" open>
    <summary><span className="status-dot" /><span>برنامهٔ اجرا</span><span className="task-state">{task.interaction === 'chat' ? 'آخرین درخواست اجرایی' : STATUS[task.status]}</span></summary>
    <div className="task-details-body">
      {task.plan?.length > 0 ? <ol className="plan-list">{task.plan.map((step, index) => <li key={index} className={`step-${step.status}`}>
        <span className="step-indicator">{step.status === 'completed' ? <Icon name="check" size={12} /> : index + 1}</span>
        <span dir="auto">{step.title}</span><span className="step-status">{{ pending: 'در صف', running: 'در حال انجام', completed: 'انجام شد', incomplete: 'ناقص' }[step.status]}</span>
      </li>)}</ol> : <p className="muted">در حال دریافت برنامه از ایجنت…</p>}
      <div className="task-limits"><span>چرخهٔ اصلاح: {task.correction_cycles ?? 0} / {task.correction_limit ?? 3}</span>
        {task.skills?.length > 0 && <span dir="ltr">Skills: {task.skills.map(skill => skill.name).join(', ')}</span>}</div>
      {task.skill_warnings?.map((warning, index) => <p className="warning-text" key={index}>{warning}</p>)}
      {task.events?.length > 0 && <details className="tool-details"><summary>پیشرفت و خروجی ابزارها</summary><pre dir="ltr">{task.events.join('\n\n')}</pre></details>}
      {task.report && <div className="execution-report"><h3>گزارش نتیجه</h3>
        <p>فایل‌های تغییرکرده: <bdi dir="ltr">{task.report.changed_files.join(', ') || 'ندارد'}</bdi></p>
        {[...task.report.skipped_checks, ...task.report.unresolved].map((issue, index) => <p className="warning-text" dir="auto" key={index}>{issue}</p>)}
      </div>}
    </div>
  </details>;
}

export default function Workbench() {
  const [health, setHealth] = useState('در حال اتصال…');
  const [connected, setConnected] = useState(false);
  const [selection, setSelection] = useState(null);
  const [project, setProject] = useState(null);
  const [task, setTask] = useState(null);
  const [input, setInput] = useState('');
  const [mode, setMode] = useState('chat');
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [smoke, setSmoke] = useState(null);
  const [treeVersion, setTreeVersion] = useState(0);
  const [requestedFile, setRequestedFile] = useState(null);
  const [activePath, setActivePath] = useState('');
  const [explorerVisible, setExplorerVisible] = useState(true);
  const [chatVisible, setChatVisible] = useState(true);
  const explorerPanel = useRef(null);
  const chatPanel = useRef(null);
  const lock = useRef(false);
  const completedTree = useRef('');
  const bottom = useRef(null);
  const active = Boolean(task && ACTIVE.includes(task.status));
  const locked = Boolean(active || busy);

  function togglePanel(ref, visible) {
    if (visible) ref.current?.collapse();
    else ref.current?.expand();
  }
  useEffect(() => {
    const adapt = () => {
      if (window.innerWidth < 1050) explorerPanel.current?.collapse();
      if (window.innerWidth < 780) chatPanel.current?.collapse();
    };
    const timer = setTimeout(adapt, 100);
    window.addEventListener('resize', adapt);
    return () => { clearTimeout(timer); window.removeEventListener('resize', adapt); };
  }, []);

  async function call(method, ...args) {
    if (!window.codix) throw new Error('این برنامه را از نسخهٔ دسکتاپ Codix باز کنید.');
    if (lock.current) throw new Error('یک عملیات در حال انجام است؛ کمی صبر کنید.');
    lock.current = true;
    setBusy(method);
    try {
      const response = await window.codix[method](...args);
      if (!response.ok) throw new Error(response.error);
      return response.data;
    } finally { lock.current = false; setBusy(''); }
  }

  async function action(method, done, ...args) {
    setError(''); setNotice('');
    try { done(await call(method, ...args)); }
    catch (failure) { setError(failure.message); }
  }

  useEffect(() => {
    let cancelled = false;
    call('health').then(data => {
      if (!cancelled) { setHealth(data.status === 'ready' ? 'متصل' : data.status); setConnected(data.status === 'ready'); }
    }).catch(failure => { if (!cancelled) setHealth(failure.message); });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!task?.task_id || !active) return;
    let cancelled = false;
    const tick = async () => {
      if (lock.current) return;
      lock.current = true;
      try {
        const result = await window.codix.taskStatus();
        if (!cancelled) {
          if (result.ok) setTask(result.data);
          else setError(result.error);
        }
      } catch { if (!cancelled) setError('دریافت وضعیت ایجنت ناموفق بود.'); }
      finally { lock.current = false; }
    };
    const timer = setInterval(tick, 700);
    tick();
    return () => { cancelled = true; clearInterval(timer); };
  }, [task?.task_id, active]);

  useEffect(() => {
    if (!active && task?.interaction === 'task' && task.report) {
      const key = `${task.task_id}:${task.status}`;
      if (key !== completedTree.current) { completedTree.current = key; setTreeVersion(value => value + 1); }
    }
  }, [active, task?.task_id, task?.status, task?.interaction]);

  useEffect(() => { bottom.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' }); }, [task?.messages?.at(-1)?.id, task?.chat_status]);

  function selectProject() {
    action('selectProject', data => {
      if (!data) return;
      setSelection(data); setProject(null); setTask(null); setSmoke(null); setInput('');
      setRequestedFile(null); setActivePath('');
      completedTree.current = '';
    });
  }

  function send(event) {
    event.preventDefault();
    if (!project || locked || !input.trim()) return;
    action(mode === 'chat' ? 'chatSend' : 'startTask', result => {
      setTask(previous => mode === 'chat' ? { ...previous, task_id: result.task_id, status: 'running', interaction: 'chat', chat_status: 'running', chat_error: '' }
        : { task_id: result.task_id, status: 'running', interaction: 'task', has_task: true, plan: [], commands: [], messages: previous?.messages || [] });
      setInput('');
    }, input.trim());
  }

  const badge = task?.status === 'awaiting_approval' ? 'در انتظار تأیید انسانی'
    : task?.chat_status === 'running' ? 'در حال پردازش پیام' : active ? 'ایجنت در حال اجراست' : 'آمادهٔ گفتگو';

  return <main className="codix-workbench" dir="ltr">
    <header className="workbench-header">
      <div className="brand"><span className="brand-mark"><Icon name="code" size={23} /></span><div><h1>Codix</h1><span>AGENT WORKSPACE</span></div></div>
      <div className="header-project" dir="rtl"><span>{project ? 'پروژهٔ فعال' : 'فضای کار'}</span><bdi dir="ltr">{project?.root || selection?.root || 'پروژه‌ای انتخاب نشده'}</bdi></div>
      <div className={`connection ${connected ? 'is-connected' : ''}`} dir="rtl"><span className="status-dot" /><span>Backend: {health}</span></div>
      <div className="panel-toggles" dir="rtl">
        <button aria-label="نمایش یا جمع کردن درخت فایل‌ها" aria-pressed={explorerVisible} onClick={() => togglePanel(explorerPanel, explorerVisible)}><Icon name="folder" size={16} /></button>
        <button aria-label="نمایش یا جمع کردن چت" aria-pressed={chatVisible} onClick={() => togglePanel(chatPanel, chatVisible)}><Icon name="chat" size={16} /></button>
      </div>
    </header>

    <ResizablePanelGroup orientation="horizontal" className="workspace-layout" id="workspace-layout">
      <ResizablePanel id="explorer" defaultSize={240} minSize={180} maxSize="40%" collapsible collapsedSize={0} panelRef={explorerPanel}
        onResize={size => setExplorerVisible(size.asPercentage > 0)}>
      <aside className="project-sidebar" dir="rtl" aria-label="فایل‌ها و پوشه‌های پروژه">
        <div className="sidebar-top"><div className="section-eyebrow"><Icon name="folder" size={17} /><h2>فایل‌های پروژه</h2></div>
          <Button variant="outline" className="project-select" onClick={selectProject} disabled={locked || !connected}><Icon name="folder" size={15} />انتخاب پوشه</Button>
          {selection && <div className="project-setup"><p className="selected-path" dir="ltr" title={selection.root}>{selection.root}</p>
            {!project && <><p className="muted">{selection.dockerfile ? 'Dockerfile پروژه پیش از ساخت و اجرا به تأیید شما نیاز دارد.' : 'محیط پیش‌فرض Node.js 22 و Python 3.12'}</p>
              <Button disabled={locked} onClick={() => action('prepareProject', setProject)}>آماده‌سازی محیط</Button></>}
            {project && <span className="project-ready"><Icon name="check" size={13} />محیط پروژه آماده است</span>}
          </div>}
        </div>
        <div className="tree-container">{project ? <FileTree key={`${project.project_id}:${treeVersion}`} readDirectory={path => call('runTool', 'list_files', { path })} locked={locked}
          onOpen={path => setRequestedFile({ path })} activePath={activePath} />
          : <div className="sidebar-empty"><Icon name="folder" size={31} /><p>فایل‌ها از پروژهٔ شما خوانده می‌شوند</p><span>{selection ? 'ابتدا محیط Docker را آماده کنید.' : 'برای نمایش ساختار، پوشهٔ پروژه را انتخاب کنید.'}</span></div>}</div>
        <div className="sidebar-bottom"><span className="section-eyebrow">محیط اجرا</span>
          <Button variant="outline" disabled={locked || !connected} onClick={() => action('prerequisites', () => setNotice('Docker با موتور Linux آماده است.'))}>بررسی Docker</Button>
          {project && <Button variant="outline" disabled={locked} onClick={() => action('smoke', data => {
            setSmoke(data); if (!data.compatible) setError('محیط انتخاب‌شده ابزارهای لازم را ندارد.');
          })}>بررسی نسخهٔ Node و Python</Button>}
          <p className="muted">فهرست فایل‌ها فقط خواندنی است.</p>
        </div>
      </aside>
      </ResizablePanel>
      <ResizableHandle aria-label="تغییر عرض درخت فایل‌ها" />
      <ResizablePanel id="work-area" minSize={280}>
        <ResizablePanelGroup orientation="vertical" id="work-area-layout">
          <ResizablePanel id="top-area" minSize={280}>
            <ResizablePanelGroup orientation="horizontal" id="files-chat-layout">
              <ResizablePanel id="files" minSize={220}>
                <FileViewer key={project?.project_id || 'no-project'} requested={requestedFile} onActivePath={setActivePath} />
              </ResizablePanel>
              <ResizableHandle aria-label="تغییر عرض چت و فایل‌ها" />
              <ResizablePanel id="chat" defaultSize={360} minSize={280} maxSize="75%" collapsible collapsedSize={0} panelRef={chatPanel}
                onResize={size => setChatVisible(size.asPercentage > 0)}>

      <section className="conversation-panel" dir="rtl" aria-label="چت با ایجنت">
        <div className="panel-heading conversation-heading"><div><Icon name="chat" size={18} /><h2>گفتگو با ایجنت</h2></div>
          <span className={`agent-state ${active ? 'is-active' : ''}`}><span className="status-dot" />{project ? badge : 'منتظر انتخاب پروژه'}</span></div>
        <div className="conversation-scroll">
          {!task?.messages?.length && <div className="chat-empty"><span className="empty-brand"><Icon name="code" size={32} /></span>
            <span className="section-eyebrow">CODIX / WORKSPACE</span><h2>از گفتگو تا اجرای تغییرات</h2>
            <p>{project ? 'پیام خود را برای ایجنت بفرستید. برای تغییر فایل‌ها یا اجرای کار، حالت «اجرای درخواست» را انتخاب کنید.' : 'پروژه را انتخاب و محیط آن را آماده کنید؛ سپس با ایجنت گفتگو کنید یا یک درخواست اجرایی بفرستید.'}</p>
            <div className="empty-caption"><Icon name="check" size={14} /><span>عملیات حساس با تأیید شما انجام می‌شوند</span></div>
          </div>}
          <div className="messages" role="log" aria-label="پیام‌های مکالمه" aria-live="polite" aria-relevant="additions text">
            {task?.messages?.map(message => <article key={message.id} className={`message message-${message.role}`} data-role={message.role}>
              <div className="message-author"><span className="message-avatar">{message.role === 'user' ? 'ش' : <Icon name="code" size={15} />}</span>
                <span>{message.role === 'user' ? 'شما' : 'Codix'}</span><span className="message-kind">{message.kind === 'task' ? (message.role === 'user' ? 'درخواست اجرا' : 'گزارش اجرا') : 'گفتگو'}</span></div>
              <div className="message-bubble"><MessageContent content={message.content} /></div>
            </article>)}
          </div>
          {task?.history_truncated && <p className="history-note">بخش قدیمی مکالمه برای رعایت محدودیت زمینه از جلسه کنار گذاشته شده است.</p>}
          {active && <div className="processing-state" role="status"><span className="processing-pulse" /><span>{badge}</span></div>}
          {task?.chat_error && <div className="workspace-error" role="alert" dir="auto"><Icon name="alert" />{task.chat_error}</div>}
          <TaskDetails task={task} />
          <div ref={bottom} />
        </div>

        <div className="composer-area">
          {error && <div className="workspace-error" role="alert"><Icon name="alert" /><span dir="auto">{error}</span><button aria-label="بستن خطا" onClick={() => setError('')}>×</button></div>}
          {notice && <p className="workspace-notice" role="status"><Icon name="check" size={15} />{notice}</p>}
          <form className={`composer ${mode === 'task' ? 'execution-mode' : ''}`} onSubmit={send}>
            <div className="composer-toolbar"><div className="mode-selector" role="tablist" aria-label="نوع پیام">
              <button type="button" role="tab" aria-selected={mode === 'chat'} disabled={locked} onClick={() => setMode('chat')}><Icon name="chat" size={14} />گفتگو</button>
              <button type="button" role="tab" aria-selected={mode === 'task'} disabled={locked} onClick={() => setMode('task')}><Icon name="code" size={15} />اجرای درخواست</button>
            </div><span className="composer-mode-hint">{mode === 'chat' ? 'بدون اجرای ابزار' : 'با برنامه و تأییدهای لازم'}</span></div>
            <label className="sr-only" htmlFor="task-request">پیام به ایجنت</label>
            <textarea id="task-request" value={input} maxLength={4000} rows={3} dir="auto" disabled={!project || locked}
              onChange={event => setInput(event.target.value)} onKeyDown={event => {
                if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); event.currentTarget.form.requestSubmit(); }
              }} placeholder={!project ? 'ابتدا پروژه را آماده کنید…' : mode === 'chat' ? 'پیام یا پرسش خود را بنویسید…' : 'تغییر مورد نظر و معیار پذیرش آن را بنویسید…'} />
            <div className="composer-bottom"><span><kbd>Enter</kbd> ارسال <span className="keyboard-separator">·</span> <kbd>Shift + Enter</kbd> خط جدید</span>
              <Button type="submit" disabled={!project || locked || !input.trim()}><Icon name={mode === 'chat' ? 'send' : 'code'} size={15} />{mode === 'chat' ? 'ارسال پیام' : 'شروع وظیفه'}</Button></div>
          </form>
          <div className="budget-strip"><span>{task ? `توکن: ${task.tokens_used ?? 0} / ${task.token_limit ?? 25000}` : 'بودجهٔ هر تسک: ۲۵٬۰۰۰ توکن'}</span>
            {task?.tokens_reported != null && <span>مصرف گزارش‌شده: {task.tokens_reported}؛ رزرو بدون گزارش مصرف: {task.tokens_reserved ?? 0}</span>}</div>
          {task?.next_call_tokens != null && <p className="warning-text">درخواست بعدی به {task.next_call_tokens} توکن بودجه نیاز داشت؛ باقی‌مانده: {(task.token_limit ?? 25000) - (task.tokens_used ?? 0)}.</p>}
        </div>
      </section>
              </ResizablePanel>
            </ResizablePanelGroup>
          </ResizablePanel>
          <ResizableHandle aria-label="تغییر ارتفاع ترمینال" />
          <ResizablePanel id="terminals" defaultSize={240} minSize={190}>
            <TerminalPanel key={project?.project_id || 'no-project'} project={project} commands={task?.commands} active={active && task?.interaction === 'task'} locked={locked} smoke={smoke} />
          </ResizablePanel>
        </ResizablePanelGroup>
      </ResizablePanel>
    </ResizablePanelGroup>
    <footer className="workbench-footer"><span><span className="status-dot" />{project ? 'Docker workspace' : 'No project selected'}</span>
      <span dir="rtl">{busy ? 'در حال ارتباط…' : active ? badge : 'آماده'}<span className="footer-divider">/</span>تأیید انسانی فعال</span></footer>
  </main>;
}
