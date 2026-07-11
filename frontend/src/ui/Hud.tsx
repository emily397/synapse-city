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
  if (!id) return null;
  const a = p?.agent;
  return (
    <div className="panel profile">
      <div className="phead">
        <h3>{a ? `${a.emoji ?? ""} ${a.name}` : id}</h3>
        <button className="ghost" onClick={() => close(null)}>✕</button>
      </div>
      {loading && <div className="pmuted">loading…</div>}
      {!loading && !p && <div className="pmuted">profile unavailable (backend offline?)</div>}
      {p && (
        <>
          <div className="pline"><b>{a.role}</b> · running <code>{a.model || "town default"}</code></div>
          <div className="pline pmuted">{a.district ? `currently in ${a.district}` : ""}</div>
          <div className="grid">
            <div><b>{Math.round(p.elo.rating)}</b><span>ELO ({p.debates.wins}W/{p.debates.losses}L)</span></div>
            <div><b>{p.memories.total}</b><span>memories</span></div>
            <div><b>{p.spoken_turns}</b><span>things said</span></div>
            <div><b>{p.conversations}</b><span>conversations</span></div>
          </div>
          {p.recent_utterances?.length > 0 && (
            <div className="psec">
              <h4>Recently said</h4>
              {p.recent_utterances.slice(0, 4).map((u: any, i: number) => (
                <div className="pquote" key={i}>
                  “{u.text?.slice(0, 140)}{u.text?.length > 140 ? "…" : ""}”
                  {u.district && <span className="pwhere"> — {u.district}</span>}
                </div>
              ))}
            </div>
          )}
          {p.recent_memories?.length > 0 && (
            <div className="psec">
              <h4>Recent memories</h4>
              {p.recent_memories.slice(0, 4).map((m: any, i: number) => (
                <div className="pquote pmem" key={i}>
                  <i>{m.kind}</i> {m.text?.slice(0, 120)}{m.text?.length > 120 ? "…" : ""}
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
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
      <div className="right"><Profile /><Loop /><Elo /></div>

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
