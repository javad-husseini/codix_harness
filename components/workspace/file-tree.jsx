'use client';

import { useEffect, useRef, useState } from 'react';
import { Icon } from './icon';

export function FileTree({ readDirectory, locked, onOpen, activePath }) {
  const [nodes, setNodes] = useState({});
  const mounted = useRef(true);
  const loading = useRef(new Set());

  async function load(path) {
    if (locked || loading.current.has(path)) return;
    loading.current.add(path);
    setNodes(current => ({ ...current, [path]: { ...current[path], open: true, loading: true, error: '' } }));
    try {
      const data = await readDirectory(path);
      if (mounted.current) setNodes(current => ({ ...current, [path]: { open: true, data, loading: false } }));
    } catch (failure) {
      if (mounted.current) setNodes(current => ({ ...current, [path]: { ...current[path], loading: false, error: failure.message } }));
    } finally { loading.current.delete(path); }
  }

  useEffect(() => { mounted.current = true; load('.'); return () => { mounted.current = false; }; }, []); // Project key remounts this component.

  function toggle(path) {
    if (!nodes[path]?.data) return load(path);
    setNodes(current => ({ ...current, [path]: { ...current[path], open: !current[path].open } }));
  }

  function branch(path, depth = 0) {
    const node = nodes[path];
    if (!node) return null;
    return <div role={depth ? 'group' : 'tree'} aria-label={depth ? undefined : 'درخت فایل‌های پروژه'}>
      {node.loading && <p className="tree-note" role="status">در حال خواندن پوشه…</p>}
      {node.error && <div className="tree-note tree-error" role="alert"><span dir="auto">{node.error}</span>
        <button disabled={locked} onClick={() => load(path)}>تلاش دوباره</button></div>}
      {node.data?.entries?.length === 0 && <p className="tree-note">این پوشه خالی است.</p>}
      {[...(node.data?.entries || [])].sort((a, b) => Number(b.directory) - Number(a.directory) || a.name.localeCompare(b.name)).map(entry => {
        const child = path === '.' ? entry.name : `${path}/${entry.name}`;
        const opened = Boolean(nodes[child]?.open);
        return <div key={child} role="treeitem" aria-expanded={entry.directory ? opened : undefined}>
          {entry.directory ? <button className="tree-row" style={{ paddingInlineStart: 12 + depth * 16 }}
            onClick={() => toggle(child)} disabled={locked && !nodes[child]?.data} title={child}>
            <Icon name="chevron" size={12} className={opened ? 'tree-chevron is-open' : 'tree-chevron'} />
            <Icon name="folder" size={16} className="folder-icon" /><span>{entry.name}</span>
          </button> : <button className={`tree-row tree-file ${activePath === child ? 'is-selected' : ''}`} style={{ paddingInlineStart: 28 + depth * 16 }} title={child} onClick={() => onOpen(child)}>
            <Icon name="file" size={15} /><span>{entry.name}</span>
          </button>}
          {entry.directory && opened && branch(child, depth + 1)}
        </div>;
      })}
      {node.data?.truncated && <p className="tree-note">فهرست به سقف داده‌های ابزار رسیده؛ همهٔ موارد نمایش داده نمی‌شوند.</p>}
    </div>;
  }

  return <div className="file-tree" dir="ltr">
    <div className="tree-root"><Icon name="folder" size={15} /><span>PROJECT ROOT</span>
      <button title="به‌روزرسانی فایل‌ها" aria-label="به‌روزرسانی فایل‌ها" disabled={locked || loading.current.size > 0} onClick={() => load('.')}><Icon name="refresh" size={14} /></button>
    </div>
    {branch('.')}
    {locked && <p className="tree-note" dir="rtl">در زمان اجرا یا پردازش پیام، فقط پوشه‌های از قبل خوانده‌شده باز می‌شوند.</p>}
  </div>;
}
