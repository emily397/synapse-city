import { useRef } from "react";
import { useFrame } from "@react-three/fiber";
import { Html } from "@react-three/drei";
import * as THREE from "three";
import { useStore } from "../store";
import { useMobile } from "../ui/useMobile";
import type { Agent } from "../types";

function seedNum(s: string) {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) % 997;
  return h;
}

function Body({ shape, color, talking }: { shape: string; color: string; talking: boolean }) {
  const mat = (
    <meshStandardMaterial color={color} emissive={color}
      emissiveIntensity={talking ? 0.8 : 0.35} roughness={0.35} metalness={0.15} />
  );
  switch (shape) {
    case "sphere":
      return <mesh position={[0, 0.95, 0]} castShadow><sphereGeometry args={[0.72, 20, 20]} />{mat}</mesh>;
    case "box":
      return <mesh position={[0, 1.0, 0]} castShadow><boxGeometry args={[1.05, 1.25, 1.05]} />{mat}</mesh>;
    case "cone":
      return <mesh position={[0, 1.05, 0]} castShadow><coneGeometry args={[0.72, 1.55, 20]} />{mat}</mesh>;
    default:
      return <mesh position={[0, 1.05, 0]} castShadow><capsuleGeometry args={[0.5, 1.0, 8, 16]} />{mat}</mesh>;
  }
}

function Hat({ kind, color }: { kind: string; color: string }) {
  switch (kind) {
    case "antenna":
      return (
        <group position={[0, 2.45, 0]}>
          <mesh><cylinderGeometry args={[0.03, 0.03, 0.5, 6]} /><meshStandardMaterial color="#3a4a63" /></mesh>
          <mesh position={[0, 0.35, 0]}><sphereGeometry args={[0.12, 12, 12]} />
            <meshStandardMaterial color={color} emissive={color} emissiveIntensity={1.2} /></mesh>
        </group>
      );
    case "cap":
      return (
        <group position={[0, 2.42, 0]}>
          <mesh><sphereGeometry args={[0.44, 16, 12, 0, Math.PI * 2, 0, Math.PI / 2]} />
            <meshStandardMaterial color={color} roughness={0.6} /></mesh>
          <mesh position={[0, -0.02, 0.34]}><boxGeometry args={[0.5, 0.06, 0.3]} />
            <meshStandardMaterial color={color} roughness={0.6} /></mesh>
        </group>
      );
    case "beanie":
      return (
        <mesh position={[0, 2.5, 0]} scale={[1, 0.7, 1]}><sphereGeometry args={[0.46, 16, 16]} />
          <meshStandardMaterial color={color} roughness={0.9} /></mesh>
      );
    case "crown":
      return (
        <mesh position={[0, 2.55, 0]}><coneGeometry args={[0.4, 0.5, 5]} />
          <meshStandardMaterial color="#ffcf5a" emissive="#ffb300" emissiveIntensity={0.5}
            metalness={0.7} roughness={0.3} /></mesh>
      );
    case "halo":
      return (
        <mesh position={[0, 2.75, 0]} rotation={[Math.PI / 2, 0, 0]}>
          <torusGeometry args={[0.34, 0.05, 12, 28]} />
          <meshStandardMaterial color="#fff2a8" emissive="#ffe066" emissiveIntensity={1.3} /></mesh>
      );
    default:
      return null;
  }
}

function Avatar({ id, mobile }: { id: string; mobile: boolean }) {
  const agent = useStore((s) => s.agents[id]) as Agent | undefined;
  const bubble = useStore((s) => s.bubbles[id]);
  const ref = useRef<THREE.Group>(null);
  const phase = seedNum(id);

  useFrame((_, dt) => {
    const g = ref.current;
    if (!g || !agent) return;
    const k = Math.min(1, dt * 2.2);
    const dx = agent.pos.x - g.position.x, dz = agent.pos.z - g.position.z;
    g.position.x += dx * k;
    g.position.z += dz * k;
    const moving = Math.hypot(dx, dz) > 0.4;
    const hop = moving ? Math.abs(Math.sin(performance.now() / 120 + phase)) * 0.3 : 0;
    g.position.y = 0.1 + hop + Math.sin(performance.now() / 380 + phase) * 0.06;
    if (Math.hypot(dx, dz) > 0.05)
      g.rotation.y += (Math.atan2(dx, dz) - g.rotation.y) * Math.min(1, dt * 4);
  });

  if (!agent) return null;
  const talking = agent.status === "interacting";
  // On phones the bubbles blanket the scene and fight the feed; the feed
  // carries every line anyway, so small screens go bubble-free.
  const showBubble = !mobile && bubble && bubble.until > Date.now();
  const av = agent.avatar || {};

  return (
    <group ref={ref} position={[agent.pos.x, 0.1, agent.pos.z]}>
      <mesh position={[0, -0.08, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <circleGeometry args={[1.0, 24]} />
        <meshBasicMaterial color={agent.color} transparent opacity={talking ? 0.55 : 0.28} />
      </mesh>
      <Body shape={av.body || "capsule"} color={agent.color} talking={talking} />
      <mesh position={[0, 2.05, 0]} castShadow>
        <sphereGeometry args={[0.42, 20, 20]} />
        <meshStandardMaterial color="#fffaf2" emissive={agent.color} emissiveIntensity={0.18} />
      </mesh>
      {[-0.16, 0.16].map((x) => (
        <mesh key={x} position={[x, 2.08, 0.37]}><sphereGeometry args={[0.06, 8, 8]} />
          <meshStandardMaterial color="#2b3448" /></mesh>
      ))}
      <Hat kind={av.hat || "none"} color={agent.color} />

      <Html position={[0, 3.05, 0]} center distanceFactor={40} style={{ pointerEvents: "none" }}>
        <div className="name-tag" style={{ borderColor: agent.color }}>
          <span>{agent.emoji}</span> <b style={{ color: agent.color }}>{agent.name}</b>
          {agent.model ? <i>{agent.model}</i> : <i>{agent.role}</i>}
        </div>
      </Html>
      {showBubble && (
        <Html position={[0, 4.0, 0]} center distanceFactor={34} style={{ pointerEvents: "none" }}>
          <div className="bubble" style={{ borderColor: agent.color }}>
            {bubble!.text.length > 140 ? bubble!.text.slice(0, 140) + "…" : bubble!.text}
          </div>
        </Html>
      )}
    </group>
  );
}

export function Agents() {
  const ids = useStore((s) => Object.keys(s.agents));
  const mobile = useMobile();
  return <>{ids.map((id) => <Avatar key={id} id={id} mobile={mobile} />)}</>;
}
