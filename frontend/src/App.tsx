import { Component, useEffect, type ReactNode } from "react";
import { Scene } from "./three/Scene";
import { Hud } from "./ui/Hud";
import { AddResident } from "./ui/AddResident";
import { useStore } from "./store";

class SceneBoundary extends Component<{ children: ReactNode }, { err: string | null }> {
  state = { err: null as string | null };
  static getDerivedStateFromError(e: any) {
    (window as any).__sceneError = e?.stack || e?.message || String(e);
    return { err: e?.message || String(e) };
  }
  render() {
    if (this.state.err) {
      return (
        <div style={{ position: "absolute", inset: 0, display: "grid",
          placeItems: "center", color: "#ff9db0", background: "#0b0e1a",
          fontFamily: "monospace", padding: 40, textAlign: "center" }}>
          3D scene error: {this.state.err}
        </div>
      );
    }
    return this.props.children;
  }
}

export function App() {
  const connect = useStore((s) => s.connect);
  useEffect(() => {
    connect();
    // Nudge react-three-fiber to measure the canvas: on some first paints its
    // ResizeObserver doesn't fire until a resize event lands.
    [0, 120, 350, 800].forEach((t) =>
      setTimeout(() => window.dispatchEvent(new Event("resize")), t));
  }, [connect]);
  return (
    <div className="app">
      <SceneBoundary><Scene /></SceneBoundary>
      <Hud />
      <AddResident />
    </div>
  );
}
