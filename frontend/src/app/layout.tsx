import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Stock Office",
  description: "AI investment office simulator — paper trading only",
  // iOS "홈 화면에 추가": full-screen app with its own icon and name.
  appleWebApp: { capable: true, title: "Stock Office", statusBarStyle: "black-translucent" },
  icons: { apple: "/icons/apple-touch-icon.png" },
  // Next emits the standard "mobile-web-app-capable"; iOS before 17.4 only reads this one.
  other: { "apple-mobile-web-app-capable": "yes" },
};

export const viewport: Viewport = {
  themeColor: "#0b1020",
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // Browser extensions add attributes to <html> before React hydrates; ignore that mismatch.
    <html lang="ko" suppressHydrationWarning>
      {/* Safe-area padding keeps content clear of the notch / home bar in the installed app. */}
      <body className="min-h-screen antialiased pt-[env(safe-area-inset-top)] pb-[env(safe-area-inset-bottom)]">{children}</body>
    </html>
  );
}
