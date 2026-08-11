import './globals.css';
import type { Metadata } from 'next';
import { ChatLayout } from '@/components/ChatLayout';

export const metadata: Metadata = {
  title: 'EaseMize Chat',
  description: 'A chat application inspired by EaseMize',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="antialiased">{children}</body>
    </html>
  );
}