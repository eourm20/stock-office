import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Stock Office",
  description: "AI investment office simulator — paper trading only",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko">
      <body className="min-h-screen antialiased">{children}</body>
    </html>
  );
}
