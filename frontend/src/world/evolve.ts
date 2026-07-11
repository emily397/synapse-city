// Client-side mirror of backend/synapse/worldgen.py so the deployed,
// backend-less preview shows the full self-evolving world loop. When a real
// backend is connected its world_update events take over and this is unused.
import type { District, Frontier, Vec, World } from "../types";

export interface Archetype {
  archetype: string; kind: string; color: string; activity: string; signal: string;
}

export const ARCHETYPES: Archetype[] = [
  { archetype: "observatory", kind: "reasoning", color: "#4fb6ff", activity: "stargazing hypotheses", signal: "sft_reasoning" },
  { archetype: "beacon",      kind: "reasoning", color: "#6ec6ff", activity: "long-sight reasoning", signal: "sft_reasoning" },
  { archetype: "foundry",     kind: "building",  color: "#ff9a52", activity: "forging build tasks", signal: "sft_procedural" },
  { archetype: "mill",        kind: "building",  color: "#ffb36b", activity: "iterating mechanisms", signal: "sft_procedural" },
  { archetype: "athenaeum",   kind: "teaching",  color: "#43df85", activity: "patient explanation", signal: "distillation" },
  { archetype: "archive",     kind: "teaching",  color: "#5fe89d", activity: "re-teaching old insight", signal: "distillation" },
  { archetype: "colosseum",   kind: "debate",    color: "#ff5d8f", activity: "formal argument", signal: "dpo_preference" },
  { archetype: "gallery",     kind: "creative",  color: "#c07bff", activity: "divergent riffs", signal: "diversity" },
  { archetype: "greenhouse",  kind: "creative",  color: "#d59aff", activity: "growing ideas under glass", signal: "diversity" },
  { archetype: "bazaar",      kind: "social",    color: "#ffd166", activity: "trading stories", signal: "none" },
  { archetype: "harbor",      kind: "social",    color: "#ffe08a", activity: "talk at the water's edge", signal: "none" },
  { archetype: "shrine",      kind: "rest",      color: "#9aa7bd", activity: "quiet reflection", signal: "reflection" },
];

const NAME_A = ["Vesper", "Ember", "Cobalt", "Meridian", "Larkspur", "Quill",
  "Halcyon", "Juniper", "Sable", "Aurora", "Fable", "Onyx", "Marigold",
  "Cinder", "Willow", "Zephyr", "Isolde", "Bramble", "Lumen", "Saffron",
  "Tidal", "Hollow", "Gilded", "Whisper"];
const NAME_B: Record<string, string> = {
  observatory: "Observatory", beacon: "Beacon", foundry: "Foundry", mill: "Mill",
  athenaeum: "Athenaeum", archive: "Archive", colosseum: "Grounds",
  gallery: "Gallery", greenhouse: "Greenhouse", bazaar: "Bazaar",
  harbor: "Harbor", shrine: "Shrine",
};
const GATE_NAMES = ["Ember Gate", "Fog Door", "Vesper Arch", "Hollow Door",
  "Starward Gate", "Quiet Door", "Bramble Gate", "Tidal Arch", "Cinder Door",
  "Lumen Gate", "Whisper Arch", "Gilded Door"];

const MIN_GAP = 17;
const STEP_OUT = 26;

let salt = 0;
function makeFrontier(from: string, fromPos: Vec, dir: number): Frontier {
  return {
    id: `gate_${from}_${salt++}`,
    from,
    name: GATE_NAMES[Math.floor(Math.random() * GATE_NAMES.length)],
    dir,
    pos: { x: +(fromPos.x + Math.cos(dir) * 12.5).toFixed(1),
           z: +(fromPos.z + Math.sin(dir) * 12.5).toFixed(1) },
  };
}

export function seedFrontiers(districts: District[]): Frontier[] {
  const outer = [...districts]
    .sort((a, b) => (b.pos.x ** 2 + b.pos.z ** 2) - (a.pos.x ** 2 + a.pos.z ** 2))
    .slice(0, 3);
  return outer.map((d) =>
    makeFrontier(d.id, d.pos, Math.atan2(d.pos.z, d.pos.x) + (Math.random() - 0.5) * 0.7));
}

export interface Expansion {
  district: District; road: [string, string];
  frontiers: Frontier[]; opened: string;
}

// activity: kind -> recent conversation count (world learns what to grow)
export function generateDistrict(world: World, frontier: Frontier,
                                 activity: Record<string, number>): Expansion | null {
  const parent = world.districts.find((d) => d.id === frontier.from)!;
  let pos: Vec | null = null;
  for (let attempt = 0; attempt < 10 && !pos; attempt++) {
    const ang = frontier.dir + (Math.random() - 0.5) * 1.1 * (1 + attempt * 0.25);
    const dist = STEP_OUT + Math.random() * 10 - 3 + attempt * 2.5;
    const cand = { x: +(parent.pos.x + Math.cos(ang) * dist).toFixed(1),
                   z: +(parent.pos.z + Math.sin(ang) * dist).toFixed(1) };
    if (world.districts.every((d) => Math.hypot(cand.x - d.pos.x, cand.z - d.pos.z) >= MIN_GAP))
      pos = cand;
  }
  if (!pos) return null;

  const supply: Record<string, number> = {};
  world.districts.forEach((d) => (supply[d.kind] = (supply[d.kind] ?? 0) + 1));
  const weights = ARCHETYPES.map((a) =>
    (1 + (activity[a.kind] ?? 0) * 0.6) / (1 + (supply[a.kind] ?? 0) * 0.5));
  let r = Math.random() * weights.reduce((a, b) => a + b, 0);
  let arch = ARCHETYPES[ARCHETYPES.length - 1];
  for (let i = 0; i < ARCHETYPES.length; i++) {
    r -= weights[i];
    if (r <= 0) { arch = ARCHETYPES[i]; break; }
  }

  const used = new Set(world.districts.map((d) => d.name));
  const fresh = NAME_A.filter((p) => ![...used].some((n) => n.includes(p)));
  const prefix = (fresh.length ? fresh : NAME_A)[Math.floor(Math.random() * (fresh.length || NAME_A.length))];
  let id = `${prefix.toLowerCase()}_${arch.archetype}`;
  let n = 2;
  while (world.districts.some((d) => d.id === id)) id = `${prefix.toLowerCase()}_${arch.archetype}${n++}`;

  const district: District = {
    id, name: `The ${prefix} ${NAME_B[arch.archetype]}`, kind: arch.kind,
    pos, color: arch.color, activity: arch.activity, signal: arch.signal,
    archetype: arch.archetype, level: 1, xp: 0,
  };
  const outAng = Math.atan2(pos.z, pos.x);
  const frontiers = [makeFrontier(id, pos, outAng + (Math.random() - 0.5))];
  if (Math.random() < 0.55)
    frontiers.push(makeFrontier(id, pos,
      outAng + (Math.random() < 0.5 ? -1 : 1) * (0.9 + Math.random() * 0.7)));

  return { district, road: [frontier.from, id], frontiers, opened: frontier.id };
}

export const LEVEL_XP = [0, 14, 40, 90];
export function levelFor(xp: number): number {
  let lvl = 1;
  LEVEL_XP.forEach((need, i) => { if (xp >= need) lvl = i + 1; });
  return Math.min(lvl, 4);
}
