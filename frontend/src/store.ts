import { create } from "zustand";
import type { World, Agent, Clock, Stats, FeedItem, District } from "./types";
import { seedFrontiers, generateDistrict, levelFor } from "./world/evolve";

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
  selectedAgent: string | null;
  profile: any | null;
  profileLoading: boolean;
  weather: { kind: string; until: number } | null;
  selectAgent: (id: string | null) => void;
  toggleRotate: () => void;
  togglePresenter: () => void;
  connect: () => void;
  apply: (ev: any) => void;
  fetchModels: () => Promise<any>;
  addResident: (spec: any) => Promise<any>;
  fireEvent: (name: string) => Promise<any>;
}

// Point the deployed frontend at a self-hosted backend with these (build-time):
//   VITE_SYNAPSE_API=http://your-nucbox:8000  VITE_SYNAPSE_WS=ws://your-nucbox:8000
const ENV: any = (import.meta as any).env || {};
let API_BASE: string = ENV.VITE_SYNAPSE_API || "";

let feedId = 0;
// Self-healing connection state: the backend's tunnel URL rotates, so on any
// disconnect we re-resolve (fresh TUNNEL fetch) and reconnect with backoff.
let liveWs: WebSocket | null = null;
let mockTimer: any = null;
let reconnectTimer: any = null;
let reconnectDelay = 5000;

function scheduleReconnect(connect: () => void, delay?: number) {
  if (reconnectTimer) return;                 // never stack retries
  const d = delay ?? reconnectDelay;
  reconnectDelay = Math.min(reconnectDelay * 2, 60000);
  reconnectTimer = setTimeout(() => { reconnectTimer = null; connect(); }, d);
}

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
  selectedAgent: null,
  profile: null,
  profileLoading: false,
  weather: null,
  selectAgent: (id) => {
    if (!id) { set({ selectedAgent: null, profile: null }); return; }
    set({ selectedAgent: id, profile: null, profileLoading: true });
    fetch(`${API_BASE}/api/agents/${id}/profile`)
      .then((r) => (r.ok ? r.json() : null))
      .then((p) => {
        if (get().selectedAgent === id) set({ profile: p, profileLoading: false });
      })
      .catch(() => set({ profileLoading: false }));
  },
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
  // God-mode one-off world events. The effect + its toast arrive over WS, so we
  // only need to POST; a failure never touches the running sim.
  fireEvent: async (name) => {
    const r = await fetch(`${API_BASE}/api/${name}`, { method: "POST" });
    if (!r.ok) throw new Error("event failed");
    return r.json();
  },

  connect: async () => {
    // Backend resolution, first healthy wins:
    //   1. ?api=/?ws= URL params (no rebuild)
    //   2. TUNNEL pointer file on GitHub main (the Nucbox supervisor pushes the
    //      current quick-tunnel URL there whenever cloudflared restarts, so the
    //      hosted frontend survives tunnel churn without redeploys)
    //   3. build-time env, then same-origin; offline mock if none respond
    const params = new URLSearchParams(location.search);
    const candidates: { api: string; ws: string }[] = [];
    if (params.get("api"))
      candidates.push({ api: params.get("api")!,
        ws: params.get("ws") || params.get("api")!.replace(/^http/, "ws") });
    try {
      const r = await fetch("https://raw.githubusercontent.com/emily397/synapse-city/main/TUNNEL?t="
        + Date.now(), { signal: AbortSignal.timeout(4000), cache: "no-store" });
      if (r.ok) {
        const u = (await r.text()).trim();
        if (u.startsWith("https://"))
          candidates.push({ api: u, ws: u.replace(/^https/, "wss") });
      }
    } catch {}
    if (ENV.VITE_SYNAPSE_API)
      candidates.push({ api: ENV.VITE_SYNAPSE_API,
        ws: ENV.VITE_SYNAPSE_WS || ENV.VITE_SYNAPSE_API.replace(/^http/, "ws") });
    const proto = location.protocol === "https:" ? "wss" : "ws";
    candidates.push({ api: "", ws: `${proto}://${location.host}` });

    let base: { api: string; ws: string } | null = null;
    for (const c of candidates) {
      try {
        const r = await fetch(`${c.api}/api/models`,
          { signal: AbortSignal.timeout(6000) });
        if (r.ok) { base = c; break; }
      } catch {}
    }
    if (!base) {
      // Nothing answers right now: show the offline mock but KEEP looking for
      // the real town; when it comes back we take over transparently.
      if (!get().world && !mockTimer) mockTimer = startMock(get().apply);
      scheduleReconnect(() => get().connect(), 30000);
      return;
    }
    API_BASE = base.api;

    fetch(`${API_BASE}/api/state`).then((r) => r.json()).then((snap) => {
      if (mockTimer) { clearInterval(mockTimer); mockTimer = null; }   // real town takes over
      get().apply(snap);
    }).catch(() => {});

    try {
      if (liveWs) { try { liveWs.onclose = null; liveWs.close(); } catch {} }
      const ws = new WebSocket(`${base.ws}/ws`);
      liveWs = ws;
      ws.onopen = () => {
        reconnectDelay = 5000;                 // healthy again: reset backoff
        if (mockTimer) { clearInterval(mockTimer); mockTimer = null; }
        set({ connected: true });
      };
      ws.onmessage = (m) => get().apply(JSON.parse(m.data));
      ws.onclose = () => {
        set({ connected: false });
        // Tunnel churned or backend restarted: re-resolve from scratch
        // (fresh TUNNEL fetch) and reconnect. The town never stays gone.
        scheduleReconnect(() => get().connect());
      };
      ws.onerror = () => { try { ws.close(); } catch {} };
    } catch {
      scheduleReconnect(() => get().connect());
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
      case "weather":
        set({ weather: ev.active
          ? { kind: ev.kind, until: Date.now() + (ev.seconds || 30) * 1000 }
          : null });
        break;
      case "snapshot": {
        const agents: Record<string, Agent> = {};
        ev.agents.forEach((a: Agent) => (agents[a.id] = a));
        set({ world: ev.world, agents, clock: ev.clock, stats: ev.stats,
              live: ev.stats?.backend !== undefined,
              weather: ev.weather
                ? { kind: ev.weather.kind, until: Date.now() + 30000 } : null });
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
      case "world_update": {
        const w = s.world;
        if (!w) break;
        if (ev.kind === "district_discovered") {
          const d: District = { ...ev.district, bornAt: Date.now() };
          set({
            world: {
              ...w,
              districts: [...w.districts, d],
              roads: [...w.roads, ev.road],
              frontiers: [
                ...(w.frontiers ?? []).filter((f) => f.id !== ev.opened),
                ...(ev.frontiers ?? []),
              ],
            },
            focus: d.pos,
            activeDistrict: d.id,
            feed: pushFeed(s.feed, {
              id: feedId++, kind: "world", color: d.color,
              name: ev.by?.name,
              text: `opened a gate. ${d.name} exists now.` }),
          });
        } else if (ev.kind === "district_levelup") {
          set({
            world: { ...w, districts: w.districts.map((d) =>
              d.id === ev.district_id ? { ...d, level: ev.level } : d) },
            feed: pushFeed(s.feed, {
              id: feedId++, kind: "world", color: ev.color,
              text: `${ev.name} grew to level ${ev.level}` }),
          });
        }
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
function startMock(apply: (ev: any) => void): any {
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

  // The offline preview runs the SAME self-evolving world loop the backend
  // does: districts earn XP from footfall and talk, curious agents open
  // frontier gates, and the generator grows the town while you watch.
  const world: World = {
    name: "Synapse City", size: { x: 80, z: 80 }, roads,
    districts: districts as District[],
    frontiers: seedFrontiers(districts as District[]),
  };
  const xp: Record<string, number> = {};
  const level: Record<string, number> = {};
  const activity: Record<string, number> = {};
  world.districts.forEach((d) => { xp[d.id] = 0; level[d.id] = 1; });

  const agents = cast.map((c, i) => ({ ...c, district: districts[i % districts.length].id,
    pos: { ...districts[i % districts.length].pos }, status: "idle", partner: null }));

  let tick = 0;
  let lastExpand = -6;
  const mockStats = () => ({
    memories: 0, interactions: Math.floor(tick / 3), exchanges: tick,
    judgements: Math.floor(tick / 8), generation: Math.floor(tick / 20),
    backend: "mock (offline preview)",
    elo: cast.map((c) => ({ model: c.id, rating: 1000, games: 0 })),
    districts: world.districts.length, gates: world.frontiers!.length,
    world_level: Object.values(level).reduce((a, b) => a + b, 0),
  });

  apply({ type: "snapshot", world, agents,
    clock: { tick: 0, day: 1, hour: 12, minute: 0, night: false, generation: 0 },
    stats: mockStats() });

  const gainXp = (id: string, amt: number) => {
    xp[id] = (xp[id] ?? 0) + amt;
    const lvl = levelFor(xp[id]);
    if (lvl > (level[id] ?? 1)) {
      level[id] = lvl;
      const d = world.districts.find((x) => x.id === id)!;
      apply({ type: "world_update", kind: "district_levelup",
        district_id: id, level: lvl, name: d.name, color: d.color });
    }
  };

  return setInterval(() => {
    tick++;
    const a = agents[Math.floor(Math.random() * agents.length)];
    const d = world.districts[Math.floor(Math.random() * world.districts.length)];
    a.district = d.id; a.pos = { ...d.pos };
    apply({ type: "move", agent: a.id, to_district: d.id, pos: d.pos });
    gainXp(d.id, 1);
    if (Math.random() < 0.6) {
      apply({ type: "speak", district: a.district, agent: a,
        text: lines[Math.floor(Math.random() * lines.length)], to: "x", turn: 0 });
      activity[d.kind] = (activity[d.kind] ?? 0) + 1;
      gainXp(d.id, 2);
    }

    // A curious resident dares a gate roughly every ~20s.
    if (world.frontiers!.length && tick - lastExpand >= 12 &&
        Math.random() < 0.22 && world.districts.length < 48) {
      const f = world.frontiers![Math.floor(Math.random() * world.frontiers!.length)];
      const exp = generateDistrict(world, f, activity);
      if (exp) {
        lastExpand = tick;
        world.districts = [...world.districts, exp.district];
        world.roads = [...world.roads, exp.road];
        world.frontiers = [
          ...world.frontiers!.filter((x) => x.id !== exp.opened), ...exp.frontiers];
        xp[exp.district.id] = 0; level[exp.district.id] = 1;
        const opener = agents[Math.floor(Math.random() * agents.length)];
        apply({ type: "world_update", kind: "district_discovered",
          district: exp.district, road: exp.road, frontiers: exp.frontiers,
          opened: exp.opened, by: opener });
        opener.district = exp.district.id; opener.pos = { ...exp.district.pos };
        apply({ type: "move", agent: opener.id, to_district: opener.district, pos: opener.pos });
      } else {
        world.frontiers = world.frontiers!.filter((x) => x.id !== f.id);
      }
    }

    const hour = (12 + Math.floor(tick / 14)) % 24;
    apply({ type: "clock", tick, day: 1 + Math.floor(tick / 336), hour,
      minute: (tick * 10) % 60, night: hour >= 22 || hour < 7,
      generation: Math.floor(tick / 20) });
    if (tick % 4 === 0) apply({ type: "stats", ...mockStats() });
  }, 1500);
}
