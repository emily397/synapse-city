import { useMemo } from "react";
import { Html, RoundedBox } from "@react-three/drei";
import { useStore } from "../store";
import type { District } from "../types";

function hash(s: string) {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }
  return () => { h = Math.imul(h ^ (h >>> 15), 2246822507); return ((h >>> 0) % 1000) / 1000; };
}

function Buildings({ d }: { d: District }) {
  const boxes = useMemo(() => {
    const rnd = hash(d.id);
    const n = 4 + Math.floor(rnd() * 3);
    return Array.from({ length: n }, () => {
      const angle = rnd() * Math.PI * 2;
      const rad = 2 + rnd() * 5;
      const h = 2 + rnd() * 7;
      return { x: Math.cos(angle) * rad, z: Math.sin(angle) * rad, h,
               w: 1.4 + rnd() * 1.8, dp: 1.4 + rnd() * 1.8 };
    });
  }, [d.id]);
  return (
    <>
      {boxes.map((b, i) => (
        <RoundedBox key={i} args={[b.w, b.h, b.dp]} radius={0.18} smoothness={2}
          position={[d.pos.x + b.x, b.h / 2, d.pos.z + b.z]} castShadow receiveShadow>
          <meshStandardMaterial color="#141a2b" emissive={d.color}
            emissiveIntensity={0.35} roughness={0.4} metalness={0.2} />
        </RoundedBox>
      ))}
    </>
  );
}

function DistrictPad({ d, active }: { d: District; active: boolean }) {
  return (
    <group>
      <mesh position={[d.pos.x, 0.05, d.pos.z]} rotation={[-Math.PI / 2, 0, 0]} receiveShadow>
        <circleGeometry args={[9, 48]} />
        <meshStandardMaterial color={d.color} emissive={d.color}
          emissiveIntensity={active ? 1.1 : 0.4} transparent opacity={active ? 0.55 : 0.28} />
      </mesh>
      <mesh position={[d.pos.x, 0.06, d.pos.z]} rotation={[-Math.PI / 2, 0, 0]}>
        <ringGeometry args={[8.6, 9.1, 48]} />
        <meshBasicMaterial color={d.color} transparent opacity={active ? 1 : 0.5} />
      </mesh>
      <Buildings d={d} />
      <Html position={[d.pos.x, 9, d.pos.z]} center distanceFactor={44}
        style={{ pointerEvents: "none" }}>
        <div className={`district-label${active ? " active" : ""}`}
             style={{ borderColor: d.color }}>
          <b style={{ color: d.color }}>{d.name}</b>
          <span>{d.activity}</span>
        </div>
      </Html>
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
        const len = Math.hypot(dx, dz);
        const ang = Math.atan2(dz, dx);
        return (
          <mesh key={i} position={[(a.pos.x + b.pos.x) / 2, 0.02, (a.pos.z + b.pos.z) / 2]}
                rotation={[-Math.PI / 2, 0, -ang]} receiveShadow>
            <planeGeometry args={[len, 2.4]} />
            <meshStandardMaterial color="#243049" emissive="#3a4d78"
              emissiveIntensity={0.25} roughness={0.9} />
          </mesh>
        );
      })}
    </>
  );
}

export function City() {
  const world = useStore((s) => s.world);
  const active = useStore((s) => s.activeDistrict);
  if (!world) return null;
  return (
    <group>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.02, 0]} receiveShadow>
        <planeGeometry args={[world.size.x * 2.4, world.size.z * 2.4]} />
        <meshStandardMaterial color="#0c1120" roughness={1} metalness={0} />
      </mesh>
      <gridHelper args={[world.size.x * 2.2, 44, "#1c2740", "#131b2e"]} position={[0, 0, 0]} />
      <Roads world={world} />
      {world.districts.map((d) => (
        <DistrictPad key={d.id} d={d} active={active === d.id} />
      ))}
    </group>
  );
}
