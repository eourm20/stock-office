"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { getInbox } from "./api";

/** The company runs two separate desks: 국장 (KRX, KRW account) and 미장 (US, USD account). */
export type Market = "KR" | "US";
export const MARKET_KO: Record<Market, string> = { KR: "국장", US: "미장" };
export const MARKET_CURRENCY: Record<Market, "KRW" | "USD"> = { KR: "KRW", US: "USD" };

/** "KR:KRX:005930" → "KR"; anything else (or nothing) → null. */
export function marketOf(instrumentId: string | null | undefined): Market | null {
  const head = (instrumentId ?? "").split(":")[0];
  return head === "KR" || head === "US" ? head : null;
}

interface MarketState {
  market: Market;
  setMarket: (m: Market) => void;
  /** Approval requests waiting, per market (shown on the switch so the other desk is not missed). */
  pending: Record<Market, number>;
  refreshPending: () => void;
}

const Ctx = createContext<MarketState | null>(null);
const KEY = "stock-office.market";

function stored(): Market {
  try {
    const v = window.localStorage.getItem(KEY);
    return v === "US" ? "US" : "KR";
  } catch {
    return "KR";
  }
}

export function MarketProvider({ children }: { children: React.ReactNode }) {
  const [market, setState] = useState<Market>("KR");
  const [pending, setPending] = useState<Record<Market, number>>({ KR: 0, US: 0 });
  useEffect(() => setState(stored()), []);
  const setMarket = useCallback((m: Market) => {
    setState(m);
    try { window.localStorage.setItem(KEY, m); } catch { /* private mode: not remembered */ }
  }, []);
  const refreshPending = useCallback(() => {
    getInbox().then((items) => {
      const count: Record<Market, number> = { KR: 0, US: 0 };
      for (const i of items) {
        const m = marketOf(i.instrument_id);
        if (m && (i.status === "PENDING" || i.status === "DEFERRED" || i.opinion_open)) count[m] += 1;
      }
      setPending(count);
    }).catch(() => {});
  }, []);
  useEffect(() => {
    refreshPending();
    const t = setInterval(refreshPending, 60_000);
    return () => clearInterval(t);
  }, [refreshPending]);
  return <Ctx.Provider value={{ market, setMarket, pending, refreshPending }}>{children}</Ctx.Provider>;
}

export function useMarket(): MarketState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useMarket outside MarketProvider");
  return v;
}

/** [국장 | 미장] with a dot for waiting approvals. */
export function MarketSwitch() {
  const { market, setMarket, pending } = useMarket();
  return (
    <div role="radiogroup" aria-label="시장" className="flex rounded-lg border border-[var(--line)] p-0.5 text-[13px]">
      {(["KR", "US"] as const).map((m) => {
        const on = market === m;
        return (
          <button key={m} role="radio" aria-checked={on} onClick={() => setMarket(m)}
                  className={`relative rounded-md px-3 py-1 font-semibold ${on ? "bg-[var(--accent)] text-black" : "text-[var(--muted)]"}`}>
            {MARKET_KO[m]}
            {pending[m] > 0 && (
              <span aria-label={`결재 대기 ${pending[m]}건`}
                    className={`ml-1 rounded-full px-1.5 text-[10px] ${on ? "bg-black/20" : "bg-amber-400 text-black"}`}>{pending[m]}</span>
            )}
          </button>
        );
      })}
    </div>
  );
}
