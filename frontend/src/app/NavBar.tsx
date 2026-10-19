"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/", label: "결재함", icon: "📥", match: (p: string) => p === "/" || p.startsWith("/inbox") },
  { href: "/office", label: "오피스", icon: "📹", match: (p: string) => p.startsWith("/office") },
  { href: "/records", label: "기록", icon: "🗂", match: (p: string) => p.startsWith("/records") },
];

/**
 * The CEO's three places: inbox (decide), office (watch, like CCTV), records (minutes).
 * Phones get an app-style bottom tab bar; company settings sit behind ⚙.
 */
export default function NavBar({ children }: { children?: React.ReactNode }) {
  const path = usePathname() ?? "/";
  return (
    <>
      <header className="flex flex-wrap items-center gap-2 border-b border-[var(--line)] bg-[#0b1020]/90 px-3 py-2 text-sm sm:gap-3 sm:px-4">
        <Link href="/" className="pixel text-[12px] text-[var(--mint)] sm:text-[13px]">STOCK OFFICE</Link>
        <nav aria-label="화면" className="hidden gap-1 sm:flex">
          {LINKS.map((l) => (
            <Link key={l.href} href={l.href} aria-current={l.match(path) ? "page" : undefined}
                  className={`rounded px-3 py-1 ${l.match(path) ? "bg-[var(--accent)] text-black" : "border border-[var(--line)]"}`}>
              {l.label}
            </Link>
          ))}
        </nav>
        <span className="rounded-full border border-[var(--line)] px-2 py-0.5 text-[11px] text-[var(--muted)]"
              title="모의투자 전용. 실제 주문을 내지 않습니다">PAPER ONLY</span>
        <div className="ml-auto flex items-center gap-2">
          {children}
          <Link href="/settings" aria-label="회사 운영" aria-current={path.startsWith("/settings") ? "page" : undefined}
                className={`rounded-lg border px-2 py-1 ${path.startsWith("/settings") ? "border-[var(--accent)] text-[var(--accent)]" : "border-[var(--line)]"}`}>⚙</Link>
        </div>
      </header>
      <nav aria-label="화면" className="fixed inset-x-0 bottom-0 z-50 grid grid-cols-3 border-t border-[var(--line)] bg-[#0b1020]/95 pb-[env(safe-area-inset-bottom)] backdrop-blur sm:hidden">
        {LINKS.map((l) => {
          const active = l.match(path);
          return (
            <Link key={l.href} href={l.href} aria-current={active ? "page" : undefined}
                  className={`flex flex-col items-center gap-0.5 py-2 text-[11px] ${active ? "text-[var(--accent)]" : "text-[var(--muted)]"}`}>
              <span aria-hidden="true" className="text-lg leading-none">{l.icon}</span>{l.label}
            </Link>
          );
        })}
      </nav>
    </>
  );
}
