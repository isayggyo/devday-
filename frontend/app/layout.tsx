import './prototype.css';
import './octi.css';
import 'katex/dist/katex.min.css';

export const metadata = { title: 'Octi — 강의의 흐름을 이어가다' };

export default function Layout({ children }: { children: React.ReactNode }) {
  return <html lang="ko"><body>{children}</body></html>;
}
