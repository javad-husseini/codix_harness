import './globals.css';

export const metadata = { title: 'Codix', description: 'Isolated project workspace' };

export default function RootLayout({ children }) {
  return <html lang="fa" dir="rtl"><body>{children}</body></html>;
}
