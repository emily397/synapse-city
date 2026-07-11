export type Vec = { x: number; z: number };

export interface District {
  id: string; name: string; kind: string; pos: Vec;
  color: string; activity: string; signal: string;
  archetype?: string; level?: number; xp?: number;
  bornAt?: number;               // client ms timestamp for the reveal animation
}
export interface Frontier {
  id: string; from: string; name: string; dir: number; pos: Vec;
}
export interface World {
  name: string; size: Vec; roads: string[][]; districts: District[];
  frontiers?: Frontier[];
}
export interface AvatarSpec { body?: string; hat?: string; }
export interface Agent {
  id: string; name: string; role: string; emoji: string; color: string;
  district: string; pos: Vec; status: string; partner: string | null;
  model?: string; avatar?: AvatarSpec;
}
export interface Clock {
  tick: number; day: number; hour: number; minute: number;
  night: boolean; generation: number;
}
export interface EloRow { model: string; rating: number; games: number; }
export interface EvalRow { gen: number; passed: number; total: number; rate: number; model: string; }
export interface Stats {
  memories: number; interactions: number; exchanges: number;
  judgements: number; generation: number; backend: string; elo: EloRow[];
  eval?: EvalRow | null; eval_history?: EvalRow[];
  districts?: number; gates?: number; world_level?: number;
}
export interface FeedItem {
  id: number; kind: string; name?: string; color?: string; text: string;
}
