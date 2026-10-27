'use client';

import { useEffect, useRef, useState } from 'react';
import { CommandPanel } from './command-panel';

async function api(method, ...args) {
  const result = await window.codix[method](...args);
  if (!result.ok) throw new Error(result.error);
  return result.data;
}

function TerminalSession({ id, visible, locked }) {
  const container = useRef(null);
  const instance = useRef(null);
  const inputRef = useRef(null);
  const [text, setText] = useState('');
  const [state, setState] = useState('running');
  const [exitCode, setExitCode] = useState(null);
  const [error, setError] = useState('');
  const [connectionError, setConnectionError] = useState('');
  const [waiting, setWaiting] = useState(false);
  const [dropped, setDropped] = useState(false);
  const resize = useRef(() => {});

  async function interrupt() {
    try { await api('terminalInterrupt', id); setError(''); }
    catch (failure) { setError(failure.message); }
  }
  useEffect(() => {
    let cancelled = false, timer, observer, terminal, fit, cursor = 0, pollTimer;
    (async () => {
      const [{ Terminal }, { FitAddon }] = await Promise.all([import('@xterm/xterm'), import('@xterm/addon-fit')]);
      if (cancelled) return;
      terminal = new Terminal({ disableStdin: true, convertEol: false, scrollback: 2000, fontSize: 12,
        fontFamily: '"Cascadia Code", Consolas, "Liberation Mono", monospace',
        theme: { background: '#111217', foreground: '#d3d7e4', cursor: '#a799ff', selectionBackground: '#514574' } });
      fit = new FitAddon(); terminal.loadAddon(fit); terminal.open(container.current); instance.current = terminal;
      // Clipboard/link handlers and raw shell input are deliberately absent.
      terminal.attachCustomKeyEventHandler(event => {
        if (event.type === 'keydown' && event.ctrlKey && event.key.toLowerCase() === 'c' && !terminal.hasSelection()) { interrupt(); return false; }
        return true;
      });
      // OSC 52 cannot write the clipboard; OSC 8 links are not opened by this viewer.
      terminal.parser.registerOscHandler(52, () => true);
      terminal.parser.registerOscHandler(8, () => true);
      resize.current = () => {
        clearTimeout(timer);
        timer = setTimeout(async () => {
          if (cancelled || !container.current?.clientWidth || !container.current?.clientHeight) return;
          fit.fit();
          try { await api('terminalResize', id, Math.min(300, Math.max(20, terminal.cols)), Math.min(120, Math.max(5, terminal.rows))); }
          catch (failure) { if (!cancelled) setConnectionError(failure.message); }
        }, 120);
      };
      observer = new ResizeObserver(() => resize.current()); observer.observe(container.current); resize.current();
      async function poll() {
        try {
          const data = await api('terminalPoll', id, cursor);
          if (cancelled) return;
          if (data.output) terminal.write(data.output);
          cursor = data.cursor;
          setState(data.state); setExitCode(data.exit_code);
          setConnectionError('');
          if (data.dropped) setDropped(true);
          if (data.state === 'running' && container.current?.clientWidth && container.current?.clientHeight
              && (data.cols !== Math.min(300, Math.max(20, terminal.cols)) || data.rows !== Math.min(120, Math.max(5, terminal.rows)))) resize.current();
        } catch (failure) { if (!cancelled) setConnectionError(failure.message); }
        if (!cancelled) pollTimer = setTimeout(poll, 300);
      }
      poll();
    })().catch(failure => setError(failure.message));
    return () => { cancelled = true; clearTimeout(timer); clearTimeout(pollTimer); observer?.disconnect(); terminal?.dispose(); instance.current = null; };
  }, [id]);
  useEffect(() => { if (visible) resize.current(); }, [visible]);

  async function submit(event) {
    event.preventDefault();
    if (locked || waiting || state !== 'running') return;
    setWaiting(true); setError('');
    try { await api('terminalInput', id, text); setText(''); inputRef.current?.focus(); }
    catch (failure) { setError(failure.message); }
    finally { setWaiting(false); }
  }
  return <section className="manual-terminal" hidden={!visible} aria-label="ترمینال دستی داخل Docker">
    <div className="terminal-status" dir="rtl"><span>{state === 'running' ? 'نشست مستقل · Docker' : state === 'exited' ? `نشست پایان یافت${exitCode == null ? '' : ` · Exit: ${exitCode}`}` : 'خطای نشست'}</span>
      <span>خروجی PTY؛ stdout و stderr ترکیبی</span><button disabled={state !== 'running'} onClick={interrupt}>Ctrl+C</button></div>
    <div className="xterm-host" dir="ltr" ref={container} />
    {dropped && <p className="terminal-warning" dir="rtl">بخشی از خروجی قدیمی به سقف بافر رسیده و حذف شده است.</p>}
    {error && <div className="terminal-error" role="alert" dir="auto">{error}</div>}
    {connectionError && <div className="terminal-error" role="status" dir="auto">{connectionError}</div>}
    <form className="terminal-input" onSubmit={submit}>
      <textarea aria-label="ورودی ترمینال" ref={inputRef} dir="ltr" rows={1} maxLength={4096} value={text}
        disabled={locked || waiting || state !== 'running'} placeholder="Input requires native approval · Enter to send" onChange={event => setText(event.target.value)}
        onKeyDown={event => {
          if (event.ctrlKey && event.key.toLowerCase() === 'c' && event.currentTarget.selectionStart === event.currentTarget.selectionEnd) { event.preventDefault(); interrupt(); }
          else if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); event.currentTarget.form.requestSubmit(); }
        }} />
      <button type="submit" disabled={locked || waiting || state !== 'running'}>{waiting ? 'منتظر تأیید…' : 'تأیید و ارسال'}</button>
    </form>
  </section>;
}

export function TerminalPanel({ project, commands, active, locked, smoke }) {
  const [sessions, setSessions] = useState([]);
  const [selected, setSelected] = useState('agent');
  const [error, setError] = useState('');
  const [opening, setOpening] = useState(false);
  const [closing, setClosing] = useState('');
  const count = useRef(0);
  async function open() {
    setOpening(true); setError('');
    try {
      const data = await api('terminalOpen');
      const item = { id: data.session_id, number: ++count.current };
      setSessions(current => [...current, item]); setSelected(item.id);
    } catch (failure) { setError(failure.message); }
    finally { setOpening(false); }
  }
  async function close(id) {
    setClosing(id); setError('');
    try {
      await api('terminalClose', id);
      setSessions(current => current.filter(item => item.id !== id));
      if (selected === id) setSelected('agent');
    } catch (failure) { setError(failure.message); }
    finally { setClosing(''); }
  }
  return <div className="terminal-panel">
    <div className="terminal-tabs" role="tablist" aria-label="ترمینال‌ها" dir="ltr">
      <button role="tab" aria-selected={selected === 'agent'} onClick={() => setSelected('agent')}>خروجی ایجنت</button>
      {sessions.map(item => <div className={`terminal-tab ${selected === item.id ? 'selected' : ''}`} key={item.id}>
        <button role="tab" aria-selected={selected === item.id} onClick={() => setSelected(item.id)}>Terminal {item.number}</button>
        <button aria-label={`بستن ترمینال ${item.number}`} disabled={Boolean(closing)} onClick={() => close(item.id)}>{closing === item.id ? '…' : '×'}</button>
      </div>)}
      <button className="terminal-add" aria-label="ترمینال جدید" title="ترمینال جدید با تأیید بومی" disabled={!project || locked || opening || sessions.length >= 4} onClick={open}>{opening ? '…' : '+'}</button>
    </div>
    {error && <div className="terminal-error" role="alert" dir="auto">{error}</div>}
    <div className="agent-terminal" hidden={selected !== 'agent'}><CommandPanel commands={commands} active={active} smoke={smoke} /></div>
    {sessions.map(item => <TerminalSession key={item.id} id={item.id} visible={selected === item.id} locked={locked} />)}
  </div>;
}
