function Text({ children }) {
  return children.split(/(`[^`\n]+`)/g).map((part, index) => part.startsWith('`') && part.endsWith('`')
    ? <code key={index} dir="ltr" className="inline-code">{part.slice(1, -1)}</code>
    : <span key={index}>{part}</span>);
}

export function MessageContent({ content }) {
  const blocks = content.split(/(```[^\n]*\n[\s\S]*?```)/g);
  return <div className="message-content">{blocks.map((block, index) => {
    const code = block.match(/^```([^\n]*)\n([\s\S]*?)```$/);
    return code ? <div className="code-block" key={index} dir="ltr">
      {code[1].trim() && <div className="code-language">{code[1].trim().slice(0, 40)}</div>}
      <pre><code>{code[2]}</code></pre>
    </div> : <p dir="auto" key={index}><Text>{block}</Text></p>;
  })}</div>;
}
