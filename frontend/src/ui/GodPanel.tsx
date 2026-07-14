import { useState } from "react";
import type { CSSProperties } from "react";
import { useStore } from "../store";

// One-off, god-like nudges to the world. Each POSTs to a backend /api/* route;
// the effect + its toast arrive back over the WebSocket, and a failed click
// never touches the running sim.
const EVENTS: { name: string; icon: string; label: string; bad?: boolean }[] = [
  { name: "harvest", icon: "🌾", label: "Bounty" },
  { name: "trees", icon: "🌲", label: "Trees" },
  { name: "rain", icon: "🌧️", label: "Rain" },
  { name: "knowledge", icon: "📚", label: "Knowledge" },
  { name: "bounty", icon: "🍲", label: "Food gift" },
  { name: "omen", icon: "🛸", label: "Sky omen" },
  { name: "flood", icon: "🌊", label: "Flood", bad: true },
  { name: "fire", icon: "🔥", label: "Fire", bad: true },
  { name: "drought", icon: "🏜️", label: "Drought", bad: true },
];

export function GodPanel() {
  const fireEvent = useStore((s) => s.fireEvent);
  const [busy, setBusy] = useState<string | null>(null);
  const [flash, setFlash] = useState<string | null>(null);

  const fire = async (name: string) => {
    if (busy) return;
    setBusy(name);
    try {
      await fireEvent(name);
      setFlash(name);
      setTimeout(() => setFlash(null), 900);
    } catch {
      /* the sim keeps running regardless */
    } finally {
      setTimeout(() => setBusy(null), 500); // brief cooldown so it's clearly one-off
    }
  };

  return (
    <div style={wrap}>
      <div style={hint}>god-mode &middot; one tap = one event</div>
      <div style={row}>
        {EVENTS.map((e) => (
          <button
            key={e.name}
            title={e.label}
            disabled={busy === e.name}
            onClick={() => fire(e.name)}
            style={{
              ...btn,
              ...(e.bad ? btnBad : btnGood),
              ...(flash === e.name ? btnFlash : {}),
              opacity: busy === e.name ? 0.45 : 1,
            }}
          >
            <span style={{ fontSize: 18, lineHeight: 1 }}>{e.icon}</span>
            <span style={lbl}>{e.label}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

const wrap: CSSProperties = {
  position: "fixed",
  left: 0,
  right: 0,
  bottom: 0,
  zIndex: 50,
  display: "flex",
  flexDirection: "column",
  alignItems: "center",
  pointerEvents: "none", // don't steal drags from the 3D canvas
  padding: "0 8px 10px",
};
const hint: CSSProperties = {
  fontSize: 9,
  letterSpacing: 1.5,
  textTransform: "uppercase",
  color: "#9fb0d6",
  opacity: 0.7,
  marginBottom: 5,
  fontFamily: "monospace",
};
const row: CSSProperties = {
  display: "flex",
  gap: 6,
  flexWrap: "wrap",
  justifyContent: "center",
  maxWidth: 760,
  pointerEvents: "auto",
  background: "rgba(11,14,26,0.72)",
  backdropFilter: "blur(8px)",
  WebkitBackdropFilter: "blur(8px)",
  border: "1px solid rgba(120,150,220,0.18)",
  borderRadius: 14,
  padding: 8,
};
const btn: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  alignItems: "center",
  gap: 2,
  minWidth: 56,
  padding: "6px 9px",
  borderRadius: 10,
  border: "1px solid transparent",
  cursor: "pointer",
  color: "#eaf0ff",
  fontFamily: "inherit",
  transition: "transform .1s ease, background .2s ease",
};
const btnGood: CSSProperties = {
  background: "rgba(60,120,85,0.35)",
  borderColor: "rgba(120,220,150,0.32)",
};
const btnBad: CSSProperties = {
  background: "rgba(150,70,80,0.35)",
  borderColor: "rgba(240,130,140,0.4)",
};
const btnFlash: CSSProperties = {
  transform: "scale(1.14)",
  background: "rgba(255,255,255,0.4)",
};
const lbl: CSSProperties = { fontSize: 10, opacity: 0.92 };
