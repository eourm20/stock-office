"use client";

import { useEffect, useRef, useState } from "react";
import { departmentStatus } from "../office/departments";
import { ZONE_KO } from "../office/names";
import type { OfficeState } from "../office/stateMachine";
import type { OfficeScene } from "./OfficeScene";

interface Props {
  state: OfficeState;
  /** false while replaying instantly or catching up: characters jump, no walking. */
  animate: boolean;
  speed: number;
  reducedMotion: boolean;
  selected: string | null;
  onAgentClick: (agentId: string) => void;
}

/** Hosts the Phaser game (client-only) and forwards state; it never touches the API. */
export default function OfficeCanvas(props: Props) {
  const host = useRef<HTMLDivElement>(null);
  const scene = useRef<OfficeScene | null>(null);
  const [zone, setZone] = useState<string | null>(null);
  const focus = (z: string | null) => { setZone(z); scene.current?.focusZone(z); };
  const board = departmentStatus(props.state);
  const progress = (z: string | null) => {
    const d = board.find((b) => b.zone === z);
    return d && d.phase !== "idle" && d.total > 0 ? ` ${d.done}/${d.total}` : "";
  };
  const latest = useRef(props);
  latest.current = props;

  useEffect(() => {
    let game: import("phaser").Game | null = null;
    let cancelled = false;
    void (async () => {
      const Phaser = (await import("phaser")).default;
      const { OfficeScene } = await import("./OfficeScene");
      if (cancelled || !host.current) return;
      const s = new OfficeScene({
        onAgentClick: (id) => latest.current.onAgentClick(id),
        onReady: () => {
          const p = latest.current;
          s.setReducedMotion(p.reducedMotion);
          s.applyState(p.state, false);
        },
      });
      scene.current = s;
      game = new Phaser.Game({
        type: Phaser.AUTO, parent: host.current, backgroundColor: "#0b1020",
        pixelArt: true, scene: s,
        scale: { mode: Phaser.Scale.RESIZE, width: "100%", height: "100%" },
      });
      if (process.env.NODE_ENV !== "production") {
        // Dev-only hook for measuring frame rate in automated checks.
        (window as unknown as { __officeGame?: unknown }).__officeGame = game;
      }
    })();
    return () => {
      cancelled = true;
      scene.current = null;
      game?.destroy(true);
    };
  }, []);

  useEffect(() => {
    scene.current?.setReducedMotion(props.reducedMotion);
  }, [props.reducedMotion]);
  useEffect(() => {
    scene.current?.setSpeed(props.speed);
  }, [props.speed]);
  useEffect(() => {
    scene.current?.setSelected(props.selected);
  }, [props.selected]);
  useEffect(() => {
    scene.current?.applyState(props.state, props.animate);
  }, [props.state, props.animate]);

  return (
    <div className="flex h-full w-full flex-col">
      <div role="group" aria-label="부서 보기" className="flex shrink-0 gap-1 overflow-x-auto border-b border-[var(--line)] bg-[#0b1020] px-2 py-1.5">
        {([[null, "전체"], ...Object.entries(ZONE_KO)] as [string | null, string][]).map(([z, label]) => (
          <button key={label} onClick={() => focus(z)} aria-pressed={zone === z}
                  className={`shrink-0 whitespace-nowrap rounded-full border px-3 py-1.5 text-xs ${zone === z ? "border-[#ffd98a] bg-[#2a2310] text-[#ffd98a]" : "border-[var(--line)] bg-[#0b1020e6] text-[var(--ink)]"}`}>
            {board.find((b) => b.zone === z)?.phase === "working" && <span aria-hidden="true" className="mr-1 inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-sky-300 align-middle" />}
            {label}<span className="text-[var(--muted)]">{progress(z)}</span>
          </button>
        ))}
      </div>
      <div className="relative min-h-0 flex-1">
      {/* touch-none: the browser must not turn pinch/drag on the canvas into page zoom/scroll. */}
      <div ref={host} className="h-full w-full touch-none" role="img"
           aria-label="AI 투자회사 사무실 장면. 같은 내용은 활동 기록에 텍스트로 제공됩니다." />
      <div className="absolute bottom-3 right-3 flex flex-col gap-1">
        <button aria-label="확대" onClick={() => scene.current?.zoomBy(1.25)}
                className="h-9 w-9 rounded-lg border border-[var(--line)] bg-[#0b1020e6] text-lg">＋</button>
        <button aria-label="축소" onClick={() => scene.current?.zoomBy(0.8)}
                className="h-9 w-9 rounded-lg border border-[var(--line)] bg-[#0b1020e6] text-lg">－</button>
      </div>
      </div>
    </div>
  );
}
