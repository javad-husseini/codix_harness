'use client';

import { useEffect, useRef, useState } from 'react';
import { Button } from '@/components/ui/button';

export default function Workspace() {
  const [health, setHealth] = useState('در حال اتصال…');
  const [selection, setSelection] = useState(null);
  const [project, setProject] = useState(null);
  const [output, setOutput] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [taskInput, setTaskInput] = useState('');
  const [task, setTask] = useState(null);
  const polling = useRef(false);
  const active = Boolean(task && ['running', 'awaiting_approval'].includes(task.status));

  useEffect(() => {
    if (!task?.task_id || !['running', 'awaiting_approval'].includes(task.status)) return;
    let cancelled = false;
    const tick = async () => {
      if (polling.current) return;
      polling.current = true;
      try {
        const result = await window.codix.taskStatus();
        if (!cancelled) {
          if (result.ok) setTask(result.data);
          else setError(result.error);
        }
      } catch { if (!cancelled) setError('دریافت وضعیت وظیفه ناموفق بود.'); }
      finally { polling.current = false; }
    };
    const timer = setInterval(tick, 700);
    tick();
    return () => { cancelled = true; clearInterval(timer); };
  }, [task?.task_id, task?.status]);

  useEffect(() => {
    let active = true;
    if (!window.codix) { setHealth('این صفحه را از اپ دسکتاپ Codix باز کنید.'); return; }
    window.codix.health().then(result => {
      if (active) setHealth(result.ok ? 'متصل' : result.error);
    }).catch(() => { if (active) setHealth('ارتباط با backend برقرار نشد.'); });
    return () => { active = false; };
  }, []);

  async function action(method, done, ...args) {
    setBusy(true); setError('');
    try {
      if (!window.codix) throw new Error('اپ دسکتاپ را اجرا کنید.');
      const result = await window.codix[method](...args);
      if (!result.ok) throw new Error(result.error);
      done(result.data);
    } catch (failure) { setError(failure.message); }
    finally { setBusy(false); }
  }

  return <main className="mx-auto max-w-4xl space-y-7 px-8 py-12">
    <header className="flex items-center justify-between border-b border-border pb-6">
      <div><h1 dir="ltr" className="text-3xl font-semibold">Codix</h1><p className="mt-2 text-sm text-neutral-400">محیط پروژه</p></div>
      <span className="text-sm" role="status">Backend: {health}</span>
    </header>
    <section className="space-y-5 rounded-xl border border-border p-6">
      <h2 className="text-xl">پروژه را انتخاب کنید</h2>
      <p className="text-sm leading-7 text-neutral-400">پوشهٔ پروژه داخل محیط Docker در دسترس قرار می‌گیرد. فایل‌های همین پوشه قابل تغییر خواهند بود.</p>
      <div className="flex flex-wrap gap-3">
        <Button disabled={busy || active} onClick={() => action('selectProject', data => {
          if (data) { setSelection(data); setProject(null); setOutput(''); }
        })}>انتخاب پوشه</Button>
        <Button variant="outline" disabled={busy || active} onClick={() => action('prerequisites', () => setOutput('Docker با موتور Linux آماده است.'))}>بررسی Docker</Button>
      </div>
      {selection && <div className="space-y-4 border-t border-border pt-4">
        <p dir="ltr" className="break-all text-sm">{selection.root}</p>
        <p className="text-sm text-neutral-400">{selection.dockerfile ? 'Dockerfile پیدا شد؛ ساخت و اجرا به تأیید شما نیاز دارد.' : 'محیط پیش‌فرض Node.js 22 و Python 3.12'}</p>
        <Button disabled={busy || active || Boolean(project)} onClick={() => action('prepareProject', setProject)}>آماده‌سازی محیط</Button>
      </div>}
    </section>
    {project && <section className="space-y-4 rounded-xl border border-border p-6">
      <h2 className="text-lg">محیط پروژه آماده است</h2>
      <Button variant="outline" disabled={busy || active} onClick={() => action('smoke', data => {
        setOutput(`${data.stdout}${data.stderr}\nExit code: ${data.exit_code}`);
        if (!data.compatible) setError('ابزارهای مورد نیاز در محیط انتخاب‌شده در دسترس نیستند. سازگاری پروژه نیاز به بررسی دارد.');
      })}>بررسی نسخهٔ Node و Python</Button>
      <label htmlFor="task-request" className="block text-sm">چه تغییری در پروژه انجام شود؟</label>
      <textarea id="task-request" value={taskInput} maxLength={4000} disabled={busy || active}
        onChange={event => setTaskInput(event.target.value)} rows={4}
        className="w-full rounded-md border border-border bg-background p-3 text-sm leading-7"
        placeholder="تغییر مورد نظر و معیار پذیرش آن را بنویسید." />
      <Button disabled={busy || active || !taskInput.trim()} onClick={() => action('startTask', result => {
        setTask({ task_id: result.task_id, status: 'running', plan: [], events: [], commands: [], issues: [] });
      }, taskInput)}>شروع وظیفه</Button>
    </section>}
    {task && <section className="space-y-4 rounded-xl border border-border p-6" aria-label="وضعیت وظیفه">
      <div className="flex flex-wrap justify-between gap-3">
        <h2 className="text-lg">{{ running: 'در حال اجرا', awaiting_approval: 'در انتظار تأیید', completed: 'انجام شد',
          incomplete: 'اعتبارسنجی ناقص', stopped: 'متوقف شد', failed: 'بررسی ناموفق', budget_exhausted: 'بودجه برای درخواست بعدی کافی نیست' }[task.status]}</h2>
        <span className="text-sm text-neutral-400">توکن: {task.tokens_used ?? 0} / {task.token_limit ?? 25000}</span>
        <span className="text-sm text-neutral-400">چرخهٔ اصلاح: {task.correction_cycles ?? 0} / {task.correction_limit ?? 3}</span>
      </div>
      {task.tokens_reported != null && <p className="text-sm text-neutral-400">
        مصرف گزارش‌شده: {task.tokens_reported}؛ رزرو بدون گزارش مصرف: {task.tokens_reserved ?? 0}
      </p>}
      {task.next_call_tokens != null && <p className="text-sm text-amber-300">
        درخواست بعدی به {task.next_call_tokens} توکن بودجه نیاز داشت؛ باقی‌مانده: {(task.token_limit ?? 25000) - (task.tokens_used ?? 0)}.
      </p>}
      {task.skills?.length > 0 && <p className="text-sm">Skills: {task.skills.map(skill => skill.name).join('، ')}</p>}
      {task.skill_warnings?.map((warning, index) => <p key={index} className="text-sm text-amber-300">{warning}</p>)}
      <ol className="list-inside list-decimal space-y-2 text-sm leading-7">{task.plan?.map((step, index) =>
        <li key={index}>{step.title} — {{ pending: 'در صف', running: 'در حال انجام', completed: 'انجام شد', incomplete: 'ناقص' }[step.status]}</li>)}</ol>
      {task.events?.length > 0 && <details><summary className="cursor-pointer text-sm">پیشرفت و خروجی ابزارها</summary>
        <pre dir="ltr" className="mt-3 max-h-80 overflow-auto text-xs leading-6">{task.events.join('\n\n')}</pre></details>}
      {task.report && <div className="space-y-3 border-t border-border pt-4">
        <h3>گزارش نتیجه</h3><p className="text-sm leading-7">{task.report.summary || 'وظیفه با وضعیت بالا پایان یافت؛ نتایج بررسی را مرور کنید.'}</p>
        <p className="text-sm">فایل‌های تغییرکرده: {task.report.changed_files.join('، ') || 'ندارد'}</p>
        {task.report.commands.map((command, index) => <pre key={index} dir="ltr" className="rounded-md bg-muted p-3 text-xs leading-6">
          {command.command}{'\nExit: '}{command.exit_code}{'\n'}{command.stdout}{command.stderr}</pre>)}
        {[...task.report.skipped_checks, ...task.report.unresolved].map((issue, index) => <p key={index} className="text-sm leading-7 text-amber-300">{issue}</p>)}
      </div>}
    </section>}
    {busy && <p role="status" className="text-sm text-neutral-400">در حال انجام عملیات…</p>}
    {error && <p role="alert" className="rounded-md border border-red-900 bg-red-950/40 p-4 text-sm leading-7">{error}</p>}
    {output && <section aria-label="خروجی بررسی" className="rounded-xl border border-border p-5"><pre dir="ltr" className="text-sm leading-7">{output}</pre></section>}
  </main>;
}
