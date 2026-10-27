import { Icon } from './icon';

export function CommandPanel({ commands = [], active, smoke }) {
  return <section className="command-panel" aria-label="خروجی دستورات" dir="rtl">
    <div className="panel-heading"><div><Icon name="terminal" size={17} /><h2>خروجی دستورات</h2>
      <span className="count-badge">{commands.length}</span></div><span className="panel-hint">فقط نمایش خروجی واقعی</span></div>
    <div className="command-scroll">
      {!commands.length && !smoke && <div className="terminal-empty"><Icon name="terminal" size={26} />
        <div><p>هنوز دستوری اجرا نشده است</p><span>{active ? 'خروجی پس از پایان دستور دریافت و نمایش داده می‌شود.' : 'دستورهای اجراشده توسط ایجنت و نتیجهٔ آن‌ها اینجا نمایش داده می‌شوند.'}</span></div>
      </div>}
      {smoke && <div className="command-record"><div className="command-meta"><span>بررسی محیط Docker</span><span dir="ltr">Exit: {smoke.exit_code}</span></div>
        {smoke.stdout && <pre dir="ltr" className="stdout">{smoke.stdout}</pre>}{smoke.stderr && <pre dir="ltr" className="stderr">{smoke.stderr}</pre>}</div>}
      {commands.map((command, index) => <article className="command-record" key={index}>
        <div className="command-meta"><span>دستور {index + 1}</span><span className={command.exit_code === 0 ? 'exit-ok' : 'exit-failed'} dir="ltr">Exit: {command.exit_code}</span></div>
        <pre className="command-line" dir="ltr"><span aria-hidden="true">› </span>{command.command}</pre>
        <div className="output-stream"><span className="stream-label" dir="ltr">stdout</span>
          {command.stdout ? <pre dir="ltr" className="stdout">{command.stdout}</pre> : <p className="muted">خروجی استاندارد خالی است.</p>}</div>
        {command.stderr && <div className="output-stream"><span className="stream-label error-label" dir="ltr">stderr</span><pre dir="ltr" className="stderr">{command.stderr}</pre></div>}
      </article>)}
    </div>
  </section>;
}
