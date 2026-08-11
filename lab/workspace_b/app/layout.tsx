import type { Metadata } from "next"
import "./globals.css"

export const metadata: Metadata = {
  title: "Interactive 3D — SplineScene Demo",
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en">
      <body className="bg-black antialiased">{children}</body>
    </html>
  )
}
