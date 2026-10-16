import type { Activity, CharacterStatus } from "./stateMachine";

/** Minimal slice of the Tiled (.tmj) JSON we rely on. */
export interface TiledObject {
  name: string;
  type?: string;
  x: number;
  y: number;
  width?: number;
  height?: number;
  properties?: { name: string; value: unknown }[];
}
export interface TiledMap {
  width: number;
  height: number;
  tilewidth: number;
  tileheight: number;
  orientation: string;
  layers: ({ name: string; type: "tilelayer"; data: number[] } |
           { name: string; type: "objectgroup"; objects: TiledObject[] })[];
}

export interface Point { x: number; y: number }
export interface Zone { name: string; x0: number; y0: number; x1: number; y1: number }

export interface OfficeLayout {
  tileW: number;
  tileH: number;
  width: number;
  height: number;
  floor: number[];
  /** Spot name → tile coordinates (tile centre). */
  spots: Record<string, Point>;
  zones: Zone[];
  furniture: { sprite: string; tile: Point }[];
}

export function parseTiledMap(map: TiledMap): OfficeLayout {
  if (map.orientation !== "isometric") throw new Error("office map must be isometric");
  const th = map.tileheight;
  const layer = (name: string) => map.layers.find((l) => l.name === name);
  const floorLayer = layer("floor");
  const objects = (name: string) => {
    const l = layer(name);
    return l && l.type === "objectgroup" ? l.objects : [];
  };
  const spots: Record<string, Point> = {};
  // Tiled isometric object coordinates are measured in tile-height units along each axis.
  for (const o of objects("spots")) spots[o.name] = { x: o.x / th + 0.5, y: o.y / th + 0.5 };
  const zones = objects("zones").map((o) => ({
    name: o.name, x0: o.x / th, y0: o.y / th,
    x1: (o.x + (o.width ?? 0)) / th, y1: (o.y + (o.height ?? 0)) / th,
  }));
  const furniture = objects("furniture").map((o) => ({
    sprite: String(o.properties?.find((p) => p.name === "sprite")?.value ?? o.name),
    tile: { x: o.x / th, y: o.y / th },
  }));
  return {
    tileW: map.tilewidth, tileH: th, width: map.width, height: map.height,
    floor: floorLayer && floorLayer.type === "tilelayer" ? floorLayer.data : [],
    spots, zones, furniture,
  };
}

/** Isometric tile coordinates → world pixels (x = 0 at the map's top corner). */
export function isoToWorld(layout: OfficeLayout, tile: Point): Point {
  return {
    x: ((tile.x - tile.y) * layout.tileW) / 2,
    y: ((tile.x + tile.y) * layout.tileH) / 2,
  };
}

export function zoneOf(layout: OfficeLayout, tile: Point): Zone | null {
  return layout.zones.find((z) => tile.x >= z.x0 && tile.x < z.x1 && tile.y >= z.y0 &&
                                   tile.y < z.y1) ?? null;
}

/** The spot a character should occupy for its current status. */
export function targetSpot(layout: OfficeLayout, agentId: string, status: CharacterStatus,
                           activity: Activity | null, current: string | null): string {
  const has = (name: string) => name in layout.spots;
  if (status === "failed" && current) return current;
  if (activity === "meet" && has(`meet:${agentId}`)) return `meet:${agentId}`;
  if (activity === "work" || activity === "meet") {
    if (has(`desk:${agentId}`)) return `desk:${agentId}`;
  }
  if (has(`home:${agentId}`)) return `home:${agentId}`;
  return has(`desk:${agentId}`) ? `desk:${agentId}` : "corridor:center";
}

/** Waypoints between two spots: through room doors and the corridor when changing rooms. */
export function planPath(layout: OfficeLayout, from: string, to: string): Point[] {
  const a = layout.spots[from];
  const b = layout.spots[to];
  if (!a || !b) return b ? [b] : [];
  const za = zoneOf(layout, a);
  const zb = zoneOf(layout, b);
  if (za?.name === zb?.name) return [b];
  const path: Point[] = [];
  const doorA = za && layout.spots[`door:${za.name}`];
  const doorB = zb && layout.spots[`door:${zb.name}`];
  const corridor = layout.spots["corridor:center"];
  if (doorA) path.push(doorA);
  if (corridor && doorA && doorB) path.push(corridor);
  if (doorB) path.push(doorB);
  path.push(b);
  return path;
}

/** Facing for a move on screen: one of the four sprite directions. */
export function facing(from: Point, to: Point): "down" | "up" | "left" | "right" {
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  if (Math.abs(dx) > Math.abs(dy) * 2) return dx > 0 ? "right" : "left";
  return dy > 0 ? "down" : "up";
}
