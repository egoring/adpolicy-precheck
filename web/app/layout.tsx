import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: '광고 정책 사전 점검',
  description: '랜딩 페이지와 광고 문구를 심사 전에 점검합니다.',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko">
      <body>{children}</body>
    </html>
  );
}
