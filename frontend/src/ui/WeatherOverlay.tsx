import { useEffect, useState } from "react";
import type { CSSProperties } from "react";
import { useStore } from "../store";

// A weather spell you can SEE — rain streaks, fire glow, rising flood, dry haze —
// driven by the backend "weather" event. Pure DOM overlay: never blocks the 3D
// canvas (pointer-events none) and can't break the scene.
const ICON: Record<string, string> = {
  rain: "🌧️", fire: "🔥", flood: "🌊", drought: "🏜️", bounty: "🌾",
};

export function WeatherOverlay() {
  const weather = useStore((s) => s.weather);
  const [, bump] = useState(0);

  // re-render to clear the overlay the moment the spell expires
  useEffect(() => {
    if (!weather) return;
    const ms = Math.max(0, weather.until - Date.now()) + 60;
    const t = setTimeout(() => bump((n) => n + 1), ms);
    return () => clearTimeout(t);
  }, [weather]);

  if (!weather || Date.now() >= weather.until) return null;
  const kind = weather.kind;

  return (
    <div style={overlay} aria-hidden="true">
      <style>{KEYFRAMES}</style>
      {kind === "rain" && <Rain />}
      {kind === "fire" && <div style={{ ...tint, ...fire }} />}
      {kind === "flood" && <div style={{ ...tint, ...flood }} />}
      {kind === "drought" && <div style={{ ...tint, ...drought }} />}
      {kind === "bounty" && <div style={{ ...tint, ...bounty }} />}
      <div style={label}>{ICON[kind] || "🌦️"} {kind}</div>
    </div>
  );
}

function Rain() {
  const drops = Array.from({ length: 80 }, (_, i) => i);
  return (
    <>
      <div style={{ ...tint, background: "rgba(40,60,95,0.20)" }} />
      {drops.map((i) => {
        const left = (i * 137.5) % 100;
        const dur = 0.5 + ((i * 7) % 10) / 20;
        const delay = ((i * 13) % 20) / 20;
        const h = 50 + ((i * 11) % 40);
        return (
          <span
            key={i}
            style={{
              position: "absolute",
              top: "-12%",
              left: `${left}%`,
              width: 1.6,
              height: h,
              background: "linear-gradient(transparent, rgba(185,215,255,0.8))",
              animation: `wc-rain ${dur}s linear ${delay}s infinite`,
            }}
          />
        );
      })}
    </>
  );
}

const KEYFRAMES = `
@keyframes wc-rain { to { transform: translateY(118vh); } }
@keyframes wc-flicker { 0%,100%{opacity:.45} 45%{opacity:.72} 70%{opacity:.5} }
@keyframes wc-heat { 0%,100%{opacity:.32} 50%{opacity:.5} }
@keyframes wc-rise { from{opacity:.15;transform:translateY(30%)} to{opacity:.5;transform:translateY(0)} }
@keyframes wc-shimmer { 0%,100%{opacity:.28} 50%{opacity:.5} }
`;

const overlay: CSSProperties = {
  position: "fixed",
  inset: 0,
  zIndex: 40,
  pointerEvents: "none",
  overflow: "hidden",
};
const tint: CSSProperties = { position: "absolute", inset: 0 };
const fire: CSSProperties = {
  background:
    "radial-gradient(120% 80% at 50% 115%, rgba(255,120,30,0.55), rgba(255,60,20,0.22) 45%, transparent 70%)",
  animation: "wc-flicker 0.35s ease-in-out infinite",
};
const flood: CSSProperties = {
  background:
    "linear-gradient(to top, rgba(30,90,160,0.55), rgba(40,110,180,0.28) 35%, transparent 60%)",
  animation: "wc-rise 2.5s ease-out infinite alternate",
};
const drought: CSSProperties = {
  background:
    "radial-gradient(140% 100% at 50% 40%, rgba(230,180,80,0.30), rgba(200,120,40,0.20) 60%, transparent 85%)",
  animation: "wc-heat 3s ease-in-out infinite",
};
const bounty: CSSProperties = {
  background:
    "radial-gradient(120% 90% at 50% 20%, rgba(255,220,120,0.35), rgba(180,230,120,0.18) 55%, transparent 80%)",
  animation: "wc-shimmer 1.8s ease-in-out infinite",
};
const label: CSSProperties = {
  position: "absolute",
  top: 12,
  left: "50%",
  transform: "translateX(-50%)",
  padding: "4px 12px",
  borderRadius: 999,
  background: "rgba(11,14,26,0.7)",
  color: "#eaf0ff",
  fontFamily: "monospace",
  fontSize: 12,
  letterSpacing: 1,
  textTransform: "uppercase",
  border: "1px solid rgba(140,170,230,0.3)",
};
