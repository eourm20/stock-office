"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/", label: "분석", match: (p: string) => p === "/" || p.startsWith("/analysis") },
  { href: "/office", label: "사무실 (회의 다시보기)", match: (p: string) => p.startsWith("/office") },
  { href: "/history", label: "기록", match: (p: string) => p.startsWith("/history") },
];

export default function NavBar({ children }: { children?: React.ReactNode }) {
  const path = usePathname() ?? "/";
  return (
    <header className="flex flex-wrap items-center gap-3 border-b border-[var(--line)] bg-[#0b1020]/90 px-4 py-2 text-sm">
      <h1 className="pixel text-[13px] text-[var(--mint)]">STOCK OFFICE</h1>
      <nav aria-label="화면" className="flex gap-1">
        {LINKS.map((l) => (
          <Link key={l.href} href={l.href} aria-current={l.match(path) ? "page" : undefined}
                className={`rounded px-2 py-1 ${l.match(path) ? "bg-[var(--accent)] text-black" : "border border-[var(--line)]"}`}>
            {l.label}
          </Link>
        ))}
      </nav>
      <span className="rounded-full border border-[var(--line)] px-2 py-0.5 text-xs text-[var(--muted)]">PAPER ONLY · 결정은 제안이며 주문 없음</span>
      {children}
    </header>
  );
}
