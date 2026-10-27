'use client';

import { useEffect, useRef, useState } from 'react';
import { Icon } from './icon';

export function FileViewer({ requested, onActivePath }) {
  const [tabs, setTabs] = useState([]);
  const [active, setActive] = useState('');
  const mounted = useRef(true);
  const pending = useRef(new Set());
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => { onActivePath(active); }, [active]);

  async function load(path) {
    if (pending.current.has(path)) return;
    pending.current.add(path);
    setTabs(current => current.map(tab => tab.path === path ? { path, loading: true } : tab));
    try {
      const response = await window.codix.readFile(path);
      if (!response.ok) throw new Error(response.error);
      if (mounted.current) setTabs(current => current.map(tab => tab.path === path ? { path, ...response.data } : tab));
    } catch (error) {
      if (mounted.current) setTabs(current => current.map(tab => tab.path === path ? { path, error: error.message } : tab));
    } finally { pending.current.delete(path); }
  }

  useEffect(() => {
    if (!requested?.path) return;
    const path = requested.path;
    setActive(path);
    if (!tabs.some(tab => tab.path === path)) {
      setTabs(current => [...current, { path, loading: true }]);
      load(path);
    }
  }, [requested]);

  function close(path) {
    const remaining = tabs.filter(tab => tab.path !== path);
    setTabs(remaining);
    if (active === path) setActive(remaining.at(-1)?.path || '');
  }
  const tab = tabs.find(item => item.path === active);
  return <section className="file-viewer" aria-label="نمایش فایل فقط خواندنی">
    <div className="file-tabs" role="tablist" aria-label="فایل‌های باز" dir="ltr">
      {tabs.map(item => <div className={`file-tab ${item.path === active ? 'selected' : ''}`} key={item.path}>
        <button role="tab" aria-selected={item.path === active} onClick={() => setActive(item.path)} title={item.path}><Icon name="file" size={14} />{item.path.split('/').at(-1)}</button>
        <button aria-label={`بستن ${item.path}`} onClick={() => close(item.path)}>×</button>
      </div>)}
      {!tabs.length && <span className="tab-placeholder" dir="rtl">فایل‌های پروژه</span>}
    </div>
    {tab ? <>
      <div className="file-path"><span dir="ltr" title={tab.path}>{tab.path}</span><span dir="rtl">فقط خواندنی</span>
        <button aria-label="خواندن دوبارهٔ فایل" disabled={tab.loading} onClick={() => load(tab.path)}><Icon name="refresh" size={14} /></button></div>
      {tab.loading ? <div className="viewer-state" role="status" dir="rtl">در حال خواندن فایل…</div>
        : tab.error ? <div className="viewer-state" role="alert" dir="rtl"><p dir="auto">{tab.error}</p><button onClick={() => load(tab.path)}>تلاش دوباره</button></div>
        : tab.status === 'binary' ? <div className="viewer-state" dir="rtl">این فایل باینری است یا متن UTF-8 نیست و قابل نمایش نیست.</div>
        : tab.status === 'too_large' ? <div className="viewer-state" dir="rtl">اندازهٔ فایل از سقف نمایش ۳۲ کیبی‌بایت بیشتر است.</div>
        : <pre className="file-content" dir="ltr" tabIndex={0} aria-label={`محتوای ${tab.path}`}><code>{tab.content}</code></pre>}
    </> : <div className="viewer-state viewer-empty" dir="rtl"><Icon name="file" size={36} /><h2>فایل‌های پروژه، کنار گفتگو</h2><p>برای دیدن محتوا روی یک فایل در درخت پروژه کلیک کنید.</p><span>نمایش متن فقط خواندنی است.</span></div>}
  </section>;
}
