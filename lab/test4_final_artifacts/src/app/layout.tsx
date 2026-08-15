import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Form / Motion — Video Material Studies",
  description: "Four immersive films exploring nature, objects, texture, and machinery.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
