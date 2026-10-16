"use client";

import { useEffect, useRef } from "react";
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
    <div ref={host} className="h-full w-full" role="img"
         aria-label="AI 투자회사 사무실 장면. 같은 내용은 오른쪽 활동 기록에 텍스트로 제공됩니다." />
  );
}
