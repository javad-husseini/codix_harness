const paths = {
  chat: <><path d="M21 11.5a8.4 8.4 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.4 8.4 0 0 1-3.8-.9L3 21l1.9-5.7a8.4 8.4 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.4 8.4 0 0 1 3.8-.9h.5a8.5 8.5 0 0 1 8 8v.5Z" /></>,
  folder: <path d="M3 7a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2v10H3Z" />,
  file: <><path d="M14 3H5v18h14V8Z" /><path d="M14 3v5h5M8 13h8M8 17h5" /></>,
  chevron: <path d="m9 5 7 7-7 7" />,
  terminal: <><path d="m4 6 6 6-6 6M13 18h7" /></>,
  send: <><path d="m22 2-7 20-4-9L2 9Z" /><path d="M22 2 11 13" /></>,
  refresh: <><path d="M20 7v5h-5M4 17v-5h5" /><path d="M6.1 7a7 7 0 0 1 11.6-2L20 8M4 16l2.3 3A7 7 0 0 0 17.9 17" /></>,
  code: <><path d="m7 6-6 6 6 6m10-12 6 6-6 6m-3-15-4 18" /></>,
  check: <path d="m5 12 4 4L19 6" />,
  alert: <><path d="m12 3 10 18H2Z" /><path d="M12 9v4m0 4h.01" /></>,
};

export function Icon({ name, size = 18, className = '' }) {
  return <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" className={className}>{paths[name] || paths.code}</svg>;
}
