export type Vec = { x: number; z: number };

export interface District {
  id: string; name: string; kind: string; pos: Vec;
  color: string; activity: string; signal: string;
}
export interface World {
  name: string; size: Vec; roads: string[][]; districts: District[];
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
}
export interface FeedItem {
  id: number; kind: string; name?: string; color?: string; text: string;
}
