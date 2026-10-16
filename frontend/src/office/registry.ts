/**
 * Character Registry: appearance only. Maps agent_id → character_id → asset.
 * Swapping art means editing public/characters/registry.json; agents and events are untouched.
 */
export type Action = "idle" | "walk" | "work" | "talk";
export type Direction = "down" | "up" | "left" | "right";

export interface AnimationSpec { row: number; frames: number; fps: number }
export interface SpriteMetadata {
  frame_width: number;
  frame_height: number;
  animations: Partial<Record<Action, Partial<Record<Direction, AnimationSpec>>>>;
}

export interface CharacterEntry {
  id: string;
  name: string;
  asset: { id: string; kind: "sprite_sheet" | "static_png"; image: string; metadata?: string };
  license: { source: string; license: string; placeholder?: boolean };
}

export interface Registry {
  version: number;
  default_character: string;
  characters: CharacterEntry[];
  assignments: Record<string, string>;
}

export function characterFor(registry: Registry, agentId: string): CharacterEntry {
  const byId = (id: string) => registry.characters.find((c) => c.id === id);
  const assigned = registry.assignments[agentId];
  const entry = (assigned && byId(assigned)) || byId(registry.default_character);
  if (!entry) throw new Error(`registry has no default character ${registry.default_character}`);
  return entry;
}

/**
 * Resolve an animation, falling back so partial sheets still work:
 * requested action/direction → same action facing down → idle in that direction → idle down →
 * a single frame (static PNG).
 */
export function resolveAnimation(meta: SpriteMetadata | null, action: Action,
                                 direction: Direction): AnimationSpec {
  const anims = meta?.animations ?? {};
  return anims[action]?.[direction] ?? anims[action]?.down ?? anims.idle?.[direction] ??
    anims.idle?.down ?? { row: 0, frames: 1, fps: 1 };
}

export function frameRange(meta: SpriteMetadata | null, spec: AnimationSpec,
                           sheetWidth: number): { start: number; end: number } {
  const perRow = meta ? Math.max(1, Math.floor(sheetWidth / meta.frame_width)) : 1;
  const start = spec.row * perRow;
  return { start, end: start + Math.max(1, spec.frames) - 1 };
}
