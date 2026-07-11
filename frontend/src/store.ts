import { create } from "zustand";
import type { World, Agent, Clock, Stats, FeedItem } from "./types";

interface State {
  connected: boolean;
  live: boolean;                       // true once real backend events arrive
  world: World | null;
  agents: Record<string, Agent>;
  clock: Clock | null;
  stats: Stats | null;
  feed: FeedItem[];
  bubbles: Record<string, { text: string; until: number }>;
  activeDistrict: string | null;
  focus: { x: number; z: number } | null;
  presenter: boolean;
  autoRotate: boolean;
  toggleRotate: () => void;
  togglePresenter: () => void;
  connect: () => void;
  apply: (ev: any) => void;
  fetchModels: () => Promise<any>;
  addResident: (spec: any) => Promise<any>;
}

// Point the deployed frontend at a self-hosted backend with these (build-time):
//   VITE_SYNAPSE_API=http://your-nucbox:8000  VITE_SYNAPSE_WS=ws://your-nucbox:8000
const ENV: any = (import.meta as any).env || {};
const API_BASE: string = ENV.VITE_SYNAPSE_API || "";

let feedId = 0;

export const useStore = create<State>((set, get) => ({
  connected: false,
  live: false,
  world: null,
  agents: {},
  clock: null,
  stats: null,
  feed: [],
  bubbles: {},
  activeDistrict: null,
  focus: null,
  presenter: true,
  autoRotate: true,
  toggleRotate: () => set((s) => ({ autoRotate: !s.autoRotate })),
  togglePresenter: () => set((s) => ({ presenter: !s.presenter })),

  fetchModels: async () => {
    const r = await fetch(`${API_BASE}/api/models`);
    if (!r.ok) throw new Error("no backend");
    return r.json();
  },
  addResident: async (spec) => {
    const r = await fetch(`${API_BASE}/api/agents`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(spec),
    });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || "add failed");
    return r.json();   // the new resident also arrives over WS as agent_added
  },

  connect: () => {
    // Try REST snapshot first for an instant paint, then open the WS stream.
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const wsUrl = ENV.VITE_SYNAPSE_WS
      ? `${ENV.VITE_SYNAPSE_WS}/ws`
      : `${proto}://${location.host}/ws`;

    fetch(`${API_BASE}/api/state`).then((r) => r.json()).then((snap) => get().apply(snap))
      .catch(() => startMock(get().apply));

    try {
      const ws = new WebSocket(wsUrl);
      ws.onopen = () => set({ connected: true });
      ws.onmessage = (m) => get().apply(JSON.parse(m.data));
      ws.onclose = () => set({ connected: false });
      ws.onerror = () => { if (!get().world) startMock(get().apply); };
    } catch {
      startMock(get().apply);
    }
  },

  apply: (ev) => {
    const s = get();
    const dpos = (id: string) =>
      s.world?.districts.find((d) => d.id === id)?.pos ?? s.focus;
    switch (ev.type) {
      case "interaction_start":
        set({ activeDistrict: ev.district, focus: dpos(ev.district) });
        break;
      case "agent_added":
        set({
          agents: { ...s.agents, [ev.agent.id]: ev.agent },
          feed: pushFeed(s.feed, { id: feedId++, kind: "join", color: ev.agent.color,
            text: `${ev.agent.name} moved into town (${ev.agent.model || "model"})` }),
        });
        break;
      case "toast":
        set({ feed: pushFeed(s.feed, { id: feedId++, kind: "toast",
          color: "#8fb4ff", text: ev.text }) });
        break;
      case "snapshot": {
        const agents: Record<string, Agent> = {};
        ev.agents.forEach((a: Agent) => (agents[a.id] = a));
        set({ world: ev.world, agents, clock: ev.clock, stats: ev.stats,
              live: ev.stats?.backend !== undefined });
        break;
      }
      case "move": {
        const a = s.agents[ev.agent];
        if (a) set({ agents: { ...s.agents, [ev.agent]:
          { ...a, district: ev.to_district, pos: ev.pos } } });
        break;
      }
      case "speak": {
        const id = ev.agent.id;
        const a = s.agents[id];
        const agents = a ? { ...s.agents, [id]: { ...a, ...ev.agent } } : s.agents;
        set({
          agents,
          activeDistrict: ev.district,
          focus: dpos(ev.district),
          bubbles: { ...s.bubbles, [id]: { text: ev.text, until: Date.now() + 6000 } },
          feed: pushFeed(s.feed, {
            id: feedId++, kind: "speak", name: ev.agent.name,
            color: ev.agent.color, text: ev.text }),
        });
        break;
      }
      case "judgement":
        set({ feed: pushFeed(s.feed, { id: feedId++, kind: "judge",
          color: "#f2c94c",
          text: `${ev.a} ${ev.score_a} vs ${ev.b} ${ev.score_b}, ${ev.winner} wins` }) });
        break;
      case "reflect":
        set({ feed: pushFeed(s.feed, { id: feedId++, kind: "reflect",
          name: ev.agent.name, color: ev.agent.color, text: ev.insight }) });
        break;
      case "generation": {
        const rate = ev.eval ? `, task ${Math.round(ev.eval.rate * 100)}%` : "";
        set({ feed: pushFeed(s.feed, { id: feedId++, kind: "gen", color: "#37d67a",
          text: `Generation ${ev.generation}: ${ev.sft_count} SFT + ${ev.dpo_count} DPO${rate}` }) });
        break;
      }
      case "clock":
        set({ clock: ev });
        break;
      case "stats":
        set({ stats: ev, clock: ev.clock ?? s.clock });
        break;
    }
  },
}));

function pushFeed(feed: FeedItem[], item: FeedItem): FeedItem[] {
  return [item, ...feed].slice(0, 60);
}

// ------------------------------------------------------------------ //
// Offline mock: bundled world + random walkers so the city is alive
// without the backend. Real backend events transparently take over.
// ------------------------------------------------------------------ //
function startMock(apply: (ev: any) => void) {
  const districts = [
    { id: "lab", name: "The Lab", kind: "reasoning", pos: { x: -22, z: -20 }, color: "#3ba7ff", activity: "hypotheses", signal: "sft_reasoning" },
    { id: "workshop", name: "The Workshop", kind: "building", pos: { x: 20, z: -22 }, color: "#ff8a3d", activity: "build", signal: "sft_procedural" },
    { id: "school", name: "The School", kind: "teaching", pos: { x: -24, z: 18 }, color: "#37d67a", activity: "teach", signal: "distillation" },
    { id: "arena", name: "The Arena", kind: "debate", pos: { x: 0, z: 0 }, color: "#e0457b", activity: "debate", signal: "dpo_preference" },
    { id: "studio", name: "The Studio", kind: "creative", pos: { x: 24, z: 20 }, color: "#b76bff", activity: "create", signal: "diversity" },
    { id: "plaza", name: "The Plaza", kind: "social", pos: { x: 0, z: -30 }, color: "#f2c94c", activity: "mingle", signal: "none" },
    { id: "homes", name: "The Homes", kind: "rest", pos: { x: 0, z: 30 }, color: "#8a94a6", activity: "rest", signal: "reflection" },
  ];
  const roads = [["plaza","arena"],["arena","lab"],["arena","workshop"],["arena","school"],["arena","studio"],["arena","homes"]];
  const cast = [
    { id: "ada", name: "Ada", role: "Scientist", emoji: "🔬", color: "#3ba7ff" },
    { id: "milo", name: "Milo", role: "Engineer", emoji: "🛠️", color: "#ff8a3d" },
    { id: "sofia", name: "Sofia", role: "Teacher", emoji: "📚", color: "#37d67a" },
    { id: "rex", name: "Rex", role: "Skeptic", emoji: "⚔️", color: "#e0457b" },
    { id: "nova", name: "Nova", role: "Creative", emoji: "🎨", color: "#b76bff" },
    { id: "juno", name: "Juno", role: "Judge", emoji: "⚖️", color: "#f2c94c" },
  ];
  const lines = ["What's the actual mechanism here?", "Ship it, then measure.",
    "Think of it like a garden.", "Where's the evidence for that?",
    "What if we ran it backwards?", "Specificity wins. Marking that down."];

  const agents = cast.map((c, i) => ({ ...c, district: districts[i % districts.length].id,
    pos: { ...districts[i % districts.length].pos }, status: "idle", partner: null }));
  apply({ type: "snapshot", world: { name: "Synapse City", size: { x: 80, z: 80 }, roads, districts },
    agents, clock: { tick: 0, day: 1, hour: 12, minute: 0, night: false, generation: 0 },
    stats: { memories: 0, interactions: 0, exchanges: 0, judgements: 0, generation: 0, backend: "mock (offline preview)", elo: cast.map((c) => ({ model: c.id, rating: 1000, games: 0 })) } });

  let tick = 0;
  setInterval(() => {
    tick++;
    const a = agents[Math.floor(Math.random() * agents.length)];
    const d = districts[Math.floor(Math.random() * districts.length)];
    a.district = d.id; a.pos = { ...d.pos };
    apply({ type: "move", agent: a.id, to_district: d.id, pos: d.pos });
    if (Math.random() < 0.6) {
      apply({ type: "speak", district: a.district, agent: a,
        text: lines[Math.floor(Math.random() * lines.length)], to: "x", turn: 0 });
    }
    apply({ type: "clock", tick, day: 1, hour: (12 + Math.floor(tick / 6)) % 24,
      minute: (tick * 10) % 60, night: false, generation: Math.floor(tick / 20) });
  }, 1500);
}
