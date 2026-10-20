import Phaser from "phaser";
import { facing, isoToWorld, parseTiledMap, planPath, targetSpot, zoneOf, type OfficeLayout,
  type Point, type TiledMap } from "../office/layout";
import { characterFor, frameRange, resolveAnimation, type Action, type Direction,
  type Registry, type SpriteMetadata } from "../office/registry";
import type { CharacterState, CharacterStatus, OfficeState } from "../office/stateMachine";
import { agentShortName, TOOL_NAME_KO, ZONE_KO } from "../office/names";
import { STATION_AGENTS } from "../office/roster";

/**
 * Renders office state. It never calls the API or decides anything: every change of what a
 * character is doing comes from `applyState`. Walking is presentation only and is skipped when
 * motion is reduced or playback is instant, so the scene can always catch up.
 */

const FOOTPRINT: Record<string, number> = { desk: 1, server_rack: 1, archive: 1, meeting_table: 2 };
/** Centre of the boardroom table (tile coordinates), so people at the table face each other. */
const MEETING_CENTER: Record<string, Point> = { boardroom: { x: 11, y: 20 } };
const STANCE_COLOR: Record<string, number> = {
  bull: 0x2f9c5c, bear: 0xb84a52, aggressive: 0xd9822b, conservative: 0x3b7dd8, neutral: 0x8a8fa3,
};
const STATUS_ICON: Record<CharacterStatus, [string, string]> = {
  working: ["…", "#9fd3ff"], talking: ["", "#ffffff"], done: ["✓", "#5cddb3"],
  failed: ["!", "#ff6b6b"], idle: ["", "#ffffff"],
};
const WALK_PX_PER_SEC = 110;
/** Long walks (e.g. a desk to the boardroom) speed up to finish within this time: motion is cosmetic. */
const MAX_WALK_MS = 3500;

interface View {
  agentId: string;
  sprite: Phaser.GameObjects.Sprite;
  label: Phaser.GameObjects.Text;
  icon: Phaser.GameObjects.Text;
  bubble: Phaser.GameObjects.Container | null;
  bubbleSeq: number;
  spot: string;
  dir: Direction;
  animPrefix: string;
  moving: Phaser.Tweens.Tween | null;
}

export interface OfficeSceneHooks {
  onReady?: () => void;
  onAgentClick?: (agentId: string) => void;
}

export class OfficeScene extends Phaser.Scene {
  private layout!: OfficeLayout;
  private characterRegistry!: Registry;
  private origin: Point = { x: 0, y: 0 };
  private views = new Map<string, View>();
  private stations = new Map<string, Phaser.GameObjects.Text>();
  private pending: { state: OfficeState; animate: boolean } | null = null;
  private ready = false;
  private reducedMotion = false;
  private speed = 1;
  private selected: string | null = null;
  private selection!: Phaser.GameObjects.Graphics;
  private cursors?: Phaser.Types.Input.Keyboard.CursorKeys;
  private overview = { x: 0, y: 0, w: 1, h: 1 };

  constructor(private readonly hooks: OfficeSceneHooks = {}) {
    super("office");
  }

  preload(): void {
    this.load.json("office-map", "/office/office.tmj");
    this.load.json("registry", "/characters/registry.json");
    this.load.spritesheet("floor", "/office/floor_tiles.png", { frameWidth: 64, frameHeight: 32 });
    for (const name of ["desk", "meeting_table", "plant", "server_rack", "whiteboard", "archive"]) {
      this.load.image(`furn:${name}`, `/office/${name}.png`);
    }
  }

  create(): void {
    this.layout = parseTiledMap(this.cache.json.get("office-map") as TiledMap);
    this.characterRegistry = this.cache.json.get("registry") as Registry;
    this.origin = { x: (this.layout.height * this.layout.tileW) / 2 + 96, y: 96 };
    this.drawFloor();
    this.drawZoneLabels();
    this.drawFurniture();
    this.drawStations();
    this.selection = this.add.graphics().setDepth(1);
    this.setupCamera();

    // Character art is resolved through the registry, so it loads after the registry itself.
    for (const c of this.characterRegistry.characters) {
      this.load.image(`char-img:${c.id}`, `/characters/${c.asset.image}`);
      if (c.asset.metadata) this.load.json(`char-meta:${c.id}`, `/characters/${c.asset.metadata}`);
    }
    this.load.once(Phaser.Loader.Events.COMPLETE, () => {
      this.ready = true;
      this.hooks.onReady?.();
      if (this.pending) this.applyState(this.pending.state, this.pending.animate);
    });
    this.load.start();
  }

  update(): void {
    for (const v of this.views.values()) {
      v.sprite.setDepth(v.sprite.y);
      v.label.setPosition(v.sprite.x, v.sprite.y + 4).setDepth(v.sprite.y + 1);
      // Status icons stay above room labels and furniture so they are always readable.
      v.icon.setPosition(v.sprite.x, v.sprite.y - 70).setDepth(99_500 + v.sprite.y / 1000);
      v.bubble?.setPosition(v.sprite.x, v.sprite.y - 84);
    }
    this.selection.clear();
    const sel = this.selected ? this.views.get(this.selected) : undefined;
    if (sel) {
      this.selection.lineStyle(2, 0xffd98a, 1).strokeEllipse(sel.sprite.x, sel.sprite.y - 2, 44, 18);
      this.selection.setDepth(sel.sprite.y - 1);
    }
    const cam = this.cameras.main;
    if (this.cursors) {
      const step = 8 / cam.zoom;
      if (this.cursors.left.isDown) cam.scrollX -= step;
      if (this.cursors.right.isDown) cam.scrollX += step;
      if (this.cursors.up.isDown) cam.scrollY -= step;
      if (this.cursors.down.isDown) cam.scrollY += step;
    }
  }

  // ------------------------------------------------------------------ public API
  setReducedMotion(reduced: boolean): void {
    this.reducedMotion = reduced;
  }

  setSpeed(multiplier: number): void {
    this.speed = Math.max(1, multiplier);
  }

  /**
   * Department tabs: move the camera to one room and fit it to the view, or back to the whole
   * office (`null`). Camera only; nothing about the characters changes.
   */
  focusZone(name: string | null): void {
    const cam = this.cameras.main;
    const zone = name ? this.layout?.zones.find((z) => z.name === name) : undefined;
    let target = this.overview;
    if (zone) {
      // The four corners of the room's tile rectangle in world space.
      const corners = [[zone.x0, zone.y0], [zone.x1, zone.y0], [zone.x0, zone.y1], [zone.x1, zone.y1]]
        .map(([x, y]) => this.world({ x: x!, y: y! }));
      const xs = corners.map((c) => c.x);
      const ys = corners.map((c) => c.y);
      const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys) - 70, maxY = Math.max(...ys);
      target = { x: (minX + maxX) / 2, y: (minY + maxY) / 2, w: maxX - minX + 40, h: maxY - minY + 40 };
    }
    const zoom = Phaser.Math.Clamp(Math.min(this.scale.width / target.w, this.scale.height / target.h) * (zone ? 1 : 1.05), 0.4, 2.5);
    const ms = this.reducedMotion ? 0 : 450;
    // force: a new target (another tab, or a department walking into the boardroom) replaces a
    // camera move still in progress instead of being ignored.
    cam.pan(target.x, target.y, ms, "Sine.easeInOut", true);
    cam.zoomTo(zoom, ms, "Sine.easeInOut", true);
  }

  /** Zoom the camera by a factor (pinch, wheel, keys and the on-screen buttons). */
  zoomBy(factor: number): void {
    const cam = this.cameras.main;
    cam.setZoom(Phaser.Math.Clamp(cam.zoom * factor, 0.4, 2.5));
  }

  setSelected(agentId: string | null): void {
    this.selected = agentId;
  }

  applyState(state: OfficeState, animate: boolean): void {
    if (!this.ready) {
      this.pending = { state, animate };
      return;
    }
    const move = animate && !this.reducedMotion;
    for (const ch of Object.values(state.characters)) {
      const view = this.views.get(ch.agentId) ?? this.createView(ch);
      const target = targetSpot(this.layout, ch.agentId, ch.status, ch.activity, view.spot);
      if (target !== view.spot) this.walk(view, target, ch, move);
      else if (!view.moving) this.pose(view, ch);
      this.updateIcon(view, ch);
      this.updateBubble(view, ch);
    }
    for (const [agentId, text] of this.stations) {
      const status = state.offstage[agentId]?.status ?? "idle";
      const [icon, color] = STATUS_ICON[status];
      text.setText(`${agentShortName(agentId)} ${icon}`.trim()).setColor(status === "idle" ? "#9aa6c4" : color);
    }
  }

  // ------------------------------------------------------------------ drawing
  private world(tile: Point): Point {
    const p = isoToWorld(this.layout, tile);
    return { x: p.x + this.origin.x, y: p.y + this.origin.y };
  }

  private drawFloor(): void {
    const { width, floor } = this.layout;
    floor.forEach((gid, i) => {
      if (gid <= 0) return;
      const p = this.world({ x: (i % width) + 0.5, y: Math.floor(i / width) + 0.5 });
      this.add.image(p.x, p.y, "floor", gid - 1).setDepth(0);
    });
  }

  private drawZoneLabels(): void {
    for (const z of this.layout.zones) {
      const p = this.world({ x: z.x0 + 0.2, y: z.y0 + 0.2 });
      this.add.text(p.x, p.y - 26, ZONE_KO[z.name] ?? z.name, {
        fontFamily: "sans-serif", resolution: 2, fontSize: "13px", color: "#ffd98a",
        backgroundColor: "#0b1020cc", padding: { x: 6, y: 3 },
      }).setOrigin(0.5, 1).setDepth(99_000);
    }
  }

  private drawFurniture(): void {
    for (const f of this.layout.furniture) {
      const size = FOOTPRINT[f.sprite];
      const anchor = size
        ? this.world({ x: f.tile.x + size, y: f.tile.y + size })
        : this.world({ x: f.tile.x + 0.5, y: f.tile.y + 0.9 });
      const img = this.add.image(anchor.x, anchor.y, `furn:${f.sprite}`).setOrigin(0.5, 1);
      img.setDepth(anchor.y - (size ? (size * this.layout.tileH) / 2 : 0));
    }
  }

  /** Equipment standing in for agents without a character: a label with their live status. */
  private drawStations(): void {
    for (const agentId of STATION_AGENTS) {
      const tile = this.layout.spots[`station:${agentId}`];
      if (!tile) continue;
      const p = this.world(tile);           // spot = centre of the equipment's tile
      const text = this.add.text(p.x, p.y - 72, agentShortName(agentId), {
        fontFamily: "sans-serif", resolution: 2, fontSize: "11px", color: "#9aa6c4",
        backgroundColor: "#0b1020cc", padding: { x: 4, y: 2 },
      }).setOrigin(0.5, 1).setDepth(98_000);
      this.stations.set(agentId, text);
    }
  }

  private setupCamera(): void {
    const cam = this.cameras.main;
    const w = (this.layout.width + this.layout.height) * (this.layout.tileW / 2) + 192;
    const h = (this.layout.width + this.layout.height) * (this.layout.tileH / 2) + 192;
    cam.setBounds(-200, -200, w + 400, h + 400);
    cam.centerOn(w / 2, h / 2);
    cam.setZoom(Math.min(this.scale.width / w, this.scale.height / h) * 1.05);
    this.overview = { x: w / 2, y: h / 2, w, h };
    cam.setBackgroundColor("#0b1020");

    // Touch: one finger pans, two fingers pinch-zoom. Mouse: drag pans, wheel zooms.
    this.input.addPointer(1);
    let pinch: number | null = null;
    this.input.on("pointermove", (p: Phaser.Input.Pointer) => {
      const a = this.input.pointer1;
      const b = this.input.pointer2;
      if (a.isDown && b.isDown) {
        const dist = Phaser.Math.Distance.Between(a.x, a.y, b.x, b.y);
        if (pinch) this.zoomBy(dist / pinch);
        pinch = dist;
        return;
      }
      pinch = null;
      if (!p.isDown) return;
      cam.scrollX -= (p.x - p.prevPosition.x) / cam.zoom;
      cam.scrollY -= (p.y - p.prevPosition.y) / cam.zoom;
    });
    this.input.on("pointerup", () => { pinch = null; });
    this.input.on("wheel", (_p: unknown, _o: unknown, _dx: number, dy: number) => {
      this.zoomBy(dy > 0 ? 0.9 : 1.1);
    });
    const kb = this.input.keyboard;
    if (kb) {
      this.cursors = kb.createCursorKeys();
      kb.on("keydown-PLUS", () => cam.setZoom(Math.min(2.5, cam.zoom * 1.1)));
      kb.on("keydown-NUMPAD_ADD", () => cam.setZoom(Math.min(2.5, cam.zoom * 1.1)));
      kb.on("keydown-MINUS", () => cam.setZoom(Math.max(0.4, cam.zoom * 0.9)));
      kb.on("keydown-NUMPAD_SUBTRACT", () => cam.setZoom(Math.max(0.4, cam.zoom * 0.9)));
    }
  }

  // ------------------------------------------------------------------ characters
  private createView(ch: CharacterState): View {
    const entry = characterFor(this.characterRegistry, ch.agentId);
    const meta = (this.cache.json.get(`char-meta:${entry.id}`) as SpriteMetadata | undefined) ?? null;
    const sheetKey = `char:${entry.id}`;
    if (!this.textures.exists(sheetKey)) {
      const source = this.textures.get(`char-img:${entry.id}`).getSourceImage() as HTMLImageElement;
      const fw = meta?.frame_width ?? source.width;
      const fh = meta?.frame_height ?? source.height;
      this.textures.addSpriteSheet(sheetKey, source, { frameWidth: fw, frameHeight: fh });
      this.createAnimations(entry.id, sheetKey, meta, source.width);
    }
    const spot = targetSpot(this.layout, ch.agentId, "idle", null, null);
    const p = this.world(this.layout.spots[spot] ?? { x: 10, y: 8 });
    const sprite = this.add.sprite(p.x, p.y, sheetKey).setOrigin(0.5, 0.92);
    sprite.setInteractive({ useHandCursor: true }).on("pointerdown", () => {
      this.hooks.onAgentClick?.(ch.agentId);
    });
    const label = this.add.text(p.x, p.y, agentShortName(ch.agentId, ch.role), {
      fontFamily: "sans-serif", resolution: 2, fontSize: "11px", color: "#e8eefc",
      backgroundColor: "#0b1020aa", padding: { x: 3, y: 1 },
    }).setOrigin(0.5, 0);
    const icon = this.add.text(p.x, p.y, "", {
      fontFamily: "monospace", fontSize: "16px", color: "#ffffff", stroke: "#0b1020",
      strokeThickness: 4,
    }).setOrigin(0.5, 1);
    const view: View = { agentId: ch.agentId, sprite, label, icon, bubble: null, bubbleSeq: 0,
                         spot, dir: "down", animPrefix: entry.id, moving: null };
    this.views.set(ch.agentId, view);
    this.play(view, "idle", "down");
    return view;
  }

  private createAnimations(cid: string, sheetKey: string, meta: SpriteMetadata | null,
                           sheetWidth: number): void {
    for (const action of ["idle", "walk", "work", "talk"] as Action[]) {
      for (const dir of ["down", "up", "left", "right"] as Direction[]) {
        const spec = resolveAnimation(meta, action, dir);
        const { start, end } = frameRange(meta, spec, sheetWidth);
        this.anims.create({
          key: `${cid}:${action}:${dir}`,
          frames: this.anims.generateFrameNumbers(sheetKey, { start, end }),
          frameRate: spec.fps, repeat: -1,
        });
      }
    }
  }

  private play(view: View, action: Action, dir: Direction): void {
    view.dir = dir;
    const key = `${view.animPrefix}:${action}:${dir}`;
    if (this.reducedMotion) {
      view.sprite.anims.stop();
      view.sprite.setFrame(this.anims.get(key).frames[0]!.frame.name);
    } else if (view.sprite.anims.currentAnim?.key !== key) {
      view.sprite.play(key);
    }
  }

  private pose(view: View, ch: CharacterState): void {
    const at = this.layout.spots[view.spot];
    const center = at && MEETING_CENTER[zoneOf(this.layout, at)?.name ?? ""];
    if (ch.status === "working" && ch.activity === "work") this.play(view, "work", "up");
    else if ((ch.status === "talking" || ch.status === "working" || ch.status === "done") && ch.activity === "meet" && at) {
      const dir = center ? facing(this.world(at), this.world(center)) : "down";
      this.play(view, ch.status === "talking" ? "talk" : "idle", dir);
    } else if (ch.status === "failed") this.play(view, "idle", view.dir);
    else this.play(view, "idle", "down");
  }

  private walk(view: View, target: string, ch: CharacterState, animate: boolean): void {
    view.moving?.stop();
    view.moving = null;
    const path = planPath(this.layout, view.spot, target).map((t) => this.world(t));
    view.spot = target;
    if (!animate || path.length === 0) {
      const end = path[path.length - 1] ?? this.world(this.layout.spots[target]!);
      view.sprite.setPosition(end.x, end.y);
      this.pose(view, ch);
      return;
    }
    let total = 0;
    path.reduce((a, b) => { total += Phaser.Math.Distance.Between(a.x, a.y, b.x, b.y); return b; },
                { x: view.sprite.x, y: view.sprite.y });
    const pxPerSec = Math.max(WALK_PX_PER_SEC * this.speed, total / (MAX_WALK_MS / 1000));
    const step = (i: number) => {
      const next = path[i];
      if (!next) {
        view.moving = null;
        this.pose(view, ch);
        return;
      }
      const from = { x: view.sprite.x, y: view.sprite.y };
      const dist = Phaser.Math.Distance.Between(from.x, from.y, next.x, next.y);
      this.play(view, "walk", facing(from, next));
      view.moving = this.tweens.add({
        targets: view.sprite, x: next.x, y: next.y,
        duration: Math.max(80, (dist / pxPerSec) * 1000),
        onComplete: () => step(i + 1),
      });
    };
    step(0);
  }

  private updateIcon(view: View, ch: CharacterState): void {
    const [text, color] = STATUS_ICON[ch.status];
    if (ch.status === "working" && ch.lookup) {
      // A real tool call (tool.called): show what is being looked up instead of "…".
      const first = TOOL_NAME_KO[ch.lookup.tools[0] ?? ""] ?? "자료";
      const more = ch.lookup.tools.length > 1 ? ` 외 ${ch.lookup.tools.length - 1}` : "";
      view.icon.setText(`🔍 ${first}${more}`).setColor("#1b1405").setFontSize(12)
        .setBackgroundColor("#ffd98a").setPadding(4, 2, 4, 2).setStroke("#000000", 0);
      return;
    }
    view.icon.setText(text).setColor(color).setFontSize(16).setBackgroundColor("transparent")
      .setPadding(0, 0, 0, 0).setStroke("#0b1020", 4);
  }

  private updateBubble(view: View, ch: CharacterState): void {
    if (!ch.bubble) {
      view.bubble?.destroy();
      view.bubble = null;
      view.bubbleSeq = 0;
      return;
    }
    if (ch.bubble.seq === view.bubbleSeq) return;
    view.bubble?.destroy();
    const text = this.add.text(0, 0, ch.bubble.text, {
      fontFamily: "sans-serif", resolution: 2, fontSize: "12px", color: "#10131c",
      wordWrap: { width: 210 }, lineSpacing: 2,
    }).setOrigin(0.5, 1);
    const pad = 8;
    const g = this.add.graphics();
    const w = text.width + pad * 2;
    const h = text.height + pad * 2;
    g.fillStyle(0xffffff, 0.96).fillRoundedRect(-w / 2, -h, w, h, 8);
    g.lineStyle(2, STANCE_COLOR[ch.bubble.stance] ?? 0x3b5680, 1)
      .strokeRoundedRect(-w / 2, -h, w, h, 8);
    g.fillStyle(0xffffff, 1).fillTriangle(-6, 0, 6, 0, 0, 8);
    text.setPosition(0, -pad);
    view.bubble = this.add.container(view.sprite.x, view.sprite.y - 84, [g, text]).setDepth(100000);
    view.bubbleSeq = ch.bubble.seq;
  }
}
