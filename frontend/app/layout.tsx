import './style.css';

export const metadata = { title: 'Lecture workspace — implementation baseline' };

export default function Layout({ children }: { children: React.ReactNode }) {
  return <html lang="ko"><body>{children}</body></html>;
}
