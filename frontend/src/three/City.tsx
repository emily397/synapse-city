import { useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import { Html, RoundedBox } from "@react-three/drei";
import * as THREE from "three";
import { useStore } from "../store";
import { Landmark } from "./Landmark";
import type { District } from "../types";

function rngFrom(seed: number) {
  return () => (seed = (seed * 9301 + 49297) % 233280) / 233280;
}
function lighten(hex: string, amt = 0.35) {
  const c = new THREE.Color(hex);
  c.lerp(new THREE.Color("#ffffff"), amt);
  return c;
}
const FLOWERS = ["#ff7f9e", "#ffd24d", "#ff9a5a", "#b98bff", "#ff6f91", "#fff2a8"];

function Cottage({ pos, rot, roof, scale }:
  { pos: [number, number, number]; rot: number; roof: string; scale: number }) {
  return (
    <group position={pos} rotation={[0, rot, 0]} scale={scale}>
      <RoundedBox args={[2.4, 2.2, 2.4]} radius={0.12} smoothness={2} position={[0, 1.1, 0]}
        castShadow receiveShadow>
        <meshStandardMaterial color="#fff4e2" roughness={0.85} />
      </RoundedBox>
      <mesh position={[0, 3.0, 0]} rotation={[0, Math.PI / 4, 0]} castShadow>
        <coneGeometry args={[2.15, 1.6, 4]} />
        <meshStandardMaterial color={roof} roughness={0.7} />
      </mesh>
      <mesh position={[0, 0.55, 1.22]}>
        <boxGeometry args={[0.7, 1.05, 0.12]} />
        <meshStandardMaterial color="#7a5233" />
      </mesh>
      {[-0.72, 0.72].map((x) => (
        <mesh key={x} position={[x, 1.35, 1.22]}>
          <boxGeometry args={[0.55, 0.55, 0.12]} />
          <meshStandardMaterial color="#fff3c6" emissive="#ffcf6b" emissiveIntensity={0.7} />
        </mesh>
      ))}
      <mesh position={[0.72, 3.1, 0.4]}>
        <boxGeometry args={[0.34, 0.9, 0.34]} />
        <meshStandardMaterial color={roof} />
      </mesh>
    </group>
  );
}

function Tree({ pos, pine }: { pos: [number, number, number]; pine?: boolean }) {
  return (
    <group position={pos}>
      <mesh position={[0, pine ? 0.35 : 0.5, 0]}>
        <cylinderGeometry args={[0.16, 0.24, pine ? 0.7 : 1.0, 7]} />
        <meshStandardMaterial color="#8a5a3b" />
      </mesh>
      {pine ? (
        <mesh position={[0, 1.5, 0]} castShadow>
          <coneGeometry args={[0.9, 2.0, 8]} />
          <meshStandardMaterial color="#3fae5c" roughness={0.95} />
        </mesh>
      ) : (
        <mesh position={[0, 1.7, 0]} castShadow>
          <sphereGeometry args={[0.95, 12, 12]} />
          <meshStandardMaterial color="#57c268" roughness={0.95} />
        </mesh>
      )}
    </group>
  );
}

function Neighbourhood({ d }: { d: District }) {
  const items = useMemo(() => {
    const seed = d.id.split("").reduce((a, c) => a + c.charCodeAt(0), 0);
    const rnd = rngFrom(seed);
    const rand = (a: number, b: number) => a + rnd() * (b - a);
    const houseCount = 3 + Math.floor(rnd() * 2);
    const houses = Array.from({ length: houseCount }, (_, i) => {
      const a = (i / houseCount) * Math.PI * 2 + rnd() * 0.5;
      const rad = 4.5 + rnd() * 2.5;
      return { pos: [d.pos.x + Math.cos(a) * rad, 0, d.pos.z + Math.sin(a) * rad] as [number, number, number],
        rot: -a + Math.PI / 2 + rand(-0.3, 0.3), scale: 0.9 + rnd() * 0.35 };
    });
    const trees = Array.from({ length: 6 }, () => ({
      pos: [d.pos.x + rand(-8, 8), 0, d.pos.z + rand(-8, 8)] as [number, number, number],
      pine: rnd() < 0.5 }));
    const bushes = Array.from({ length: 4 }, () => (
      [d.pos.x + rand(-8, 8), 0.4, d.pos.z + rand(-8, 8)] as [number, number, number]));
    const flowers = Array.from({ length: 10 }, () => ({
      pos: [d.pos.x + rand(-9, 9), 0.25, d.pos.z + rand(-9, 9)] as [number, number, number],
      color: FLOWERS[Math.floor(rnd() * FLOWERS.length)] }));
    return { houses, trees, bushes, flowers };
  }, [d.id]);

  const roof = lighten(d.color, 0.25);
  return (
    <group>
      <mesh position={[d.pos.x, 0.02, d.pos.z]} rotation={[-Math.PI / 2, 0, 0]} receiveShadow>
        <circleGeometry args={[9.5, 48]} />
        <meshStandardMaterial color={d.color} transparent opacity={0.16} />
      </mesh>
      {items.houses.map((h, i) => <Cottage key={i} pos={h.pos} rot={h.rot} roof={`#${roof.getHexString()}`} scale={h.scale} />)}
      {items.trees.map((t, i) => <Tree key={i} pos={t.pos} pine={t.pine} />)}
      {items.bushes.map((p, i) => (
        <mesh key={i} position={p} castShadow><sphereGeometry args={[0.55, 10, 10]} />
          <meshStandardMaterial color="#62c46e" /></mesh>
      ))}
      {items.flowers.map((f, i) => (
        <mesh key={i} position={f.pos}><sphereGeometry args={[0.13, 8, 8]} />
          <meshStandardMaterial color={f.color} emissive={f.color} emissiveIntensity={0.25} /></mesh>
      ))}
      <Html position={[d.pos.x, 8.5, d.pos.z]} center distanceFactor={44} style={{ pointerEvents: "none" }}>
        <div className="district-label" style={{ borderColor: d.color }}>
          <b style={{ color: d.color }}>{d.name}</b>
          <span>{d.activity}</span>
        </div>
      </Html>
    </group>
  );
}

function Clouds() {
  const group = useRef<THREE.Group>(null);
  const clouds = useMemo(() => Array.from({ length: 9 }, (_, i) => {
    const r = rngFrom(i * 131 + 7);
    const puffs = Array.from({ length: 3 + Math.floor(r() * 3) }, () => ({
      p: [(r() - 0.5) * 8, (r() - 0.5) * 1.2, (r() - 0.5) * 4] as [number, number, number],
      s: 2 + r() * 1.4 }));
    return { x: (r() - 0.5) * 160, y: 26 + r() * 14, z: (r() - 0.5) * 140,
      sp: 0.6 + r() * 1.0, puffs };
  }), []);
  useFrame((_, dt) => {
    if (!group.current) return;
    group.current.children.forEach((c, i) => {
      c.position.x += clouds[i].sp * dt * 1.2;
      if (c.position.x > 95) c.position.x = -95;
    });
  });
  return (
    <group ref={group}>
      {clouds.map((c, i) => (
        <group key={i} position={[c.x, c.y, c.z]}>
          {c.puffs.map((p, j) => (
            <mesh key={j} position={p.p}><sphereGeometry args={[p.s, 10, 10]} />
              <meshStandardMaterial color="#ffffff" roughness={1} emissive="#ffffff" emissiveIntensity={0.1} /></mesh>
          ))}
        </group>
      ))}
    </group>
  );
}

function Roads({ world }: { world: any }) {
  const byId: Record<string, District> = {};
  world.districts.forEach((d: District) => (byId[d.id] = d));
  return (
    <>
      {world.roads.map((r: string[], i: number) => {
        const a = byId[r[0]], b = byId[r[1]];
        if (!a || !b) return null;
        const dx = b.pos.x - a.pos.x, dz = b.pos.z - a.pos.z;
        const len = Math.hypot(dx, dz), ang = Math.atan2(dz, dx);
        return (
          <mesh key={i} position={[(a.pos.x + b.pos.x) / 2, 0.03, (a.pos.z + b.pos.z) / 2]}
            rotation={[-Math.PI / 2, 0, -ang]} receiveShadow>
            <planeGeometry args={[len, 2.6]} />
            <meshStandardMaterial color="#e6d6ad" roughness={1} />
          </mesh>
        );
      })}
    </>
  );
}

export function City() {
  const world = useStore((s) => s.world);
  if (!world) return null;
  return (
    <group>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.02, 0]} receiveShadow>
        <circleGeometry args={[150, 64]} />
        <meshStandardMaterial color="#8fd772" roughness={1} />
      </mesh>
      <Clouds />
      <Roads world={world} />
      <group position={[0, 0, 0]} scale={2.1}><Landmark /></group>
      {world.districts.map((d) => <Neighbourhood key={d.id} d={d} />)}
    </group>
  );
}
