import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Stock Office",
  description: "AI investment office simulator — paper trading only",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // Browser extensions add attributes to <html> before React hydrates; ignore that mismatch.
    <html lang="ko" suppressHydrationWarning>
      <body className="min-h-screen antialiased">{children}</body>
    </html>
  );
}
