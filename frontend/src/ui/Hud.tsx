import { useStore } from "../store";

function Clock() {
  const c = useStore((s) => s.clock);
  if (!c) return null;
  const hh = String(c.hour).padStart(2, "0");
  const mm = String(c.minute).padStart(2, "0");
  return (
    <div className="clock">
      <span className="big">{hh}:{mm}</span>
      <span className="sub">Day {c.day} {c.night ? "🌙" : "☀️"}</span>
    </div>
  );
}

function Spark({ data }: { data: number[] }) {
  if (data.length < 2) return <div className="spark-empty">awaiting first generation</div>;
  const w = 150, h = 30;
  const pts = data.map((v, i) =>
    `${(i / (data.length - 1)) * w},${h - v * h}`).join(" ");
  return (
    <svg className="spark" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none">
      <polyline points={pts} fill="none" stroke="#37d67a" strokeWidth={2} />
    </svg>
  );
}

function Loop() {
  const st = useStore((s) => s.stats);
  const c = useStore((s) => s.clock);
  const gen = c?.generation ?? st?.generation ?? 0;
  const ev = st?.eval;
  const hist = (st?.eval_history ?? []).map((h) => h.rate);
  return (
    <div className="panel">
      <h3>Self-learning loop</h3>
      <div className="gen"><span className="genN">{gen}</span><span>generations trained</span></div>
      <div className="grid">
        <div><b>{st?.interactions ?? 0}</b><span>conversations</span></div>
        <div><b>{st?.judgements ?? 0}</b><span>debates judged</span></div>
        <div><b>{st?.exchanges ?? 0}</b><span>training rows</span></div>
        <div><b>{st?.memories ?? 0}</b><span>memories</span></div>
      </div>
      <div className="eval">
        <div className="evalhead">
          <span>task success <small>(code-verified)</small></span>
          <b>{ev ? Math.round(ev.rate * 100) : 0}%</b>
          <i>{ev ? `${ev.passed}/${ev.total}` : ""}</i>
        </div>
        <Spark data={hist} />
      </div>
      <div className="flow">
        <span>interact</span>→<span>judge</span>→<span>SFT+DPO</span>→<span>gate</span>→<span>promote</span>
      </div>
    </div>
  );
}

function Elo() {
  const st = useStore((s) => s.stats);
  const rows = [...(st?.elo ?? [])].sort((a, b) => b.rating - a.rating);
  if (!rows.length) return null;
  const max = Math.max(...rows.map((r) => r.rating), 1050);
  const min = Math.min(...rows.map((r) => r.rating), 950);
  return (
    <div className="panel">
      <h3>Debate ELO <small>(who argues best)</small></h3>
      {rows.map((r) => {
        const w = 6 + ((r.rating - min) / (max - min || 1)) * 94;
        return (
          <div className="elorow" key={r.model}>
            <span className="who">{r.model}</span>
            <div className="bar"><div style={{ width: `${w}%` }} /></div>
            <span className="rating">{Math.round(r.rating)}</span>
          </div>
        );
      })}
    </div>
  );
}

function Residents() {
  const agents = useStore((s) => s.agents);
  const select = useStore((s) => s.selectAgent);
  const selected = useStore((s) => s.selectedAgent);
  const list = Object.values(agents).sort((a: any, b: any) =>
    (b.is_judge ? 1 : 0) - (a.is_judge ? 1 : 0) || a.name.localeCompare(b.name));
  if (!list.length) return null;
  return (
    <div className="panel residents">
      <h3>Residents <small>(click one to check in)</small></h3>
      {list.map((a: any) => (
        <button
          key={a.id}
          className={`resrow${selected === a.id ? " sel" : ""}`}
          onClick={() => select(selected === a.id ? null : a.id)}
        >
          <span className="dot" style={{ background: a.color }} />
          <span className="rname">{a.emoji ?? ""} {a.name}{a.is_judge ? " ⚖️" : ""}</span>
          <span className="rmodel">{a.model || "town default"}</span>
        </button>
      ))}
    </div>
  );
}

function Profile() {
  const id = useStore((s) => s.selectedAgent);
  const p = useStore((s) => s.profile);
  const loading = useStore((s) => s.profileLoading);
  const close = useStore((s) => s.selectAgent);
  const liveAgent = useStore((s) => (id ? (s.agents as any)[id] : null));
  const activeDistrict = useStore((s) => s.activeDistrict);
  if (!id) return null;
  const a = p?.agent ?? liveAgent ?? { name: id };
  const kinds = p?.memories?.by_kind ?? {};
  const talkingNow = liveAgent?.status === "interacting";
  return (
    <>
      <div className="drawer-scrim" onClick={() => close(null)} />
      <aside className="drawer" style={{ ["--accent" as any]: a.color || "#7fd4ff" }}>
        <button className="drawer-x" onClick={() => close(null)}>✕</button>

        <div className="drawer-head">
          <div className="drawer-ava" style={{ background: `${a.color || "#7fd4ff"}22`,
            borderColor: a.color || "#7fd4ff" }}>{a.emoji ?? "🤖"}</div>
          <div className="drawer-id">
            <h2>{a.name}{a.is_judge ? " ⚖️" : ""}</h2>
            <code className="drawer-model">{a.model || "town default"}</code>
            <div className="drawer-role">{a.role}</div>
          </div>
        </div>

        <div className="drawer-now">
          <span className={`live-dot ${talkingNow ? "on" : ""}`} />
          {talkingNow
            ? <>debating right now in <b>{liveAgent?.district ?? a.district}</b></>
            : <>{liveAgent?.status ?? "resting"} in <b>{liveAgent?.district ?? a.district ?? "town"}</b></>}
        </div>

        {loading && !p && <div className="drawer-muted">reading this model's history…</div>}
        {!loading && !p && <div className="drawer-muted">history unavailable (backend offline)</div>}

        {p && (
          <>
            <section className="drawer-sec">
              <h4>In {a.name}'s own words <small>what this model actually said</small></h4>
              {p.recent_utterances?.length > 0 ? (
                p.recent_utterances.slice(0, 7).map((u: any, i: number) => (
                  <blockquote className="say" key={i}>
                    {u.text}
                    {u.district && <cite>{u.district}{u.topic ? ` · on ${u.topic}` : ""}</cite>}
                  </blockquote>
                ))
              ) : (
                <div className="drawer-muted">hasn't spoken yet, waiting for its first conversation</div>
              )}
            </section>

            <section className="drawer-sec">
              <h4>What {a.name} remembers <small>its own accumulating memory</small></h4>
              {p.recent_memories?.length > 0 ? (
                p.recent_memories.slice(0, 5).map((m: any, i: number) => (
                  <div className="mem" key={i}><i>{m.kind}</i> {m.text}</div>
                ))
              ) : <div className="drawer-muted">no memories stored yet</div>}
              {Object.keys(kinds).length > 0 && (
                <div className="mem-chips">
                  {Object.entries(kinds).map(([k, n]: any) => (
                    <span key={k} className="chip">{n} {k}</span>
                  ))}
                </div>
              )}
            </section>

            <section className="drawer-sec">
              <h4>Standing <small>progress signals for this model</small></h4>
              <div className="drawer-stats">
                <div><b>{Math.round(p.elo.rating)}</b><span>ELO</span></div>
                <div><b className="w">{p.debates.wins}</b>/<b className="l">{p.debates.losses}</b><span>win / loss</span></div>
                <div><b>{p.memories.total}</b><span>memories</span></div>
                <div><b>{p.spoken_turns}</b><span>turns spoken</span></div>
                <div><b>{p.conversations}</b><span>conversations</span></div>
                <div><b>{p.generation ?? 0}</b><span>generation</span></div>
              </div>
              <p className="drawer-note">
                Weights only change when a night training cycle promotes a new generation.
                Its words and memories above are the raw material that trains it.
              </p>
            </section>
          </>
        )}
      </aside>
    </>
  );
}

function Feed() {
  const feed = useStore((s) => s.feed);
  const icon: Record<string, string> = { speak: "💬", judge: "⚖️", reflect: "💭", gen: "📦" };
  return (
    <div className="panel feed">
      <h3>Live activity</h3>
      <div className="feed-list">
        {feed.map((f) => (
          <div className="feed-item" key={f.id}>
            <span className="dot" style={{ background: f.color ?? "#8892a6" }} />
            <span className="ftext">
              <b>{icon[f.kind] ?? "•"} {f.name ?? ""}</b> {f.text}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

export function Hud() {
  const st = useStore((s) => s.stats);
  const connected = useStore((s) => s.connected);
  const autoRotate = useStore((s) => s.autoRotate);
  const toggle = useStore((s) => s.toggleRotate);
  const presenter = useStore((s) => s.presenter);
  const togglePresenter = useStore((s) => s.togglePresenter);
  const backend = st?.backend ?? "connecting";
  return (
    <div className="hud">
      <header>
        <div className="brand">
          <h1>SYNAPSE&nbsp;CITY</h1>
          <p>a self-improving town of local models</p>
        </div>
        <div className="status">
          <span className={`badge ${connected ? "on" : "off"}`}>
            {connected ? "LIVE" : "OFFLINE PREVIEW"}
          </span>
          <span className="badge model">{backend}</span>
          <Clock />
        </div>
      </header>

      <div className="left"><Feed /><Residents /></div>
      <div className="right"><Loop /><Elo /></div>
      <Profile />

      <footer>
        <button className={`ctrl${presenter ? " active" : ""}`} onClick={togglePresenter}>
          {presenter ? "◉ presenter mode" : "○ presenter mode"}
        </button>
        {!presenter && (
          <button className="ctrl" onClick={toggle}>
            {autoRotate ? "⏸ pause orbit" : "▶ orbit camera"}
          </button>
        )}
        <span className="hint">
          {presenter
            ? "camera auto-follows the live conversation"
            : "drag to fly · scroll to zoom"}
        </span>
      </footer>
    </div>
  );
}
