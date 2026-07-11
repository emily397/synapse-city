import { useRef } from "react";
import { useFrame } from "@react-three/fiber";
import { Html } from "@react-three/drei";
import * as THREE from "three";
import type { Frontier } from "../types";

// Discovery reveal: a just-dreamed district rises out of the ground with a
// soft overshoot and an expanding light ring.
export function Reveal({ bornAt, children }:
  { bornAt?: number; children: React.ReactNode }) {
  const g = useRef<THREE.Group>(null);
  const ring = useRef<THREE.Mesh>(null);
  const done = useRef(!bornAt);
  useFrame(() => {
    if (done.current || !g.current) return;
    const t = (Date.now() - (bornAt ?? 0)) / 1600;
    if (t >= 1.6) {
      g.current.scale.setScalar(1);
      g.current.position.y = 0;
      if (ring.current) ring.current.visible = false;
      done.current = true;
      return;
    }
    const k = Math.min(1, t);
    const back = 1 + 1.7 * Math.pow(k - 1, 3) + 0.7 * Math.pow(k - 1, 2);
    g.current.scale.setScalar(Math.max(0.001, back));
    g.current.position.y = (1 - k) * -1.6;
    if (ring.current) {
      const rt = Math.min(1, t / 1.2);
      ring.current.scale.setScalar(0.5 + rt * 14);
      (ring.current.material as THREE.MeshBasicMaterial).opacity = 0.55 * (1 - rt);
    }
  });
  return (
    <group>
      <group ref={g}>{children}</group>
      {bornAt && (
        <mesh ref={ring} rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.15, 0]}>
          <ringGeometry args={[0.9, 1, 40]} />
          <meshBasicMaterial color="#ffffff" transparent opacity={0.55}
            blending={THREE.AdditiveBlending} depthWrite={false} />
        </mesh>
      )}
    </group>
  );
}

// Dream gate: an unopened door at the edge of the known world. Geometry
// follows the web3d synthesis contract: primitives only, 10-20 parts,
// frosted-glass frame, at most 3 emissive accents (#7fd4ff).
export function DreamGate({ f }: { f: Frontier }) {
  const portal = useRef<THREE.MeshStandardMaterial>(null);
  const orbs = useRef<THREE.Group>(null);
  useFrame(({ clock }) => {
    const t = clock.elapsedTime;
    if (portal.current) {
      portal.current.opacity = 0.42 + Math.sin(t * 1.7) * 0.16;
      portal.current.emissiveIntensity = 1.6 + Math.sin(t * 1.7) * 0.7;
    }
    if (orbs.current) {
      orbs.current.rotation.y = t * 0.6;
      orbs.current.position.y = 2.4 + Math.sin(t * 1.2) * 0.18;
    }
  });
  const glass = { color: "#e8edf8", transmission: 0.75, roughness: 0.35,
    ior: 1.4, thickness: 0.3, metalness: 0.6 } as const;
  return (
    <group position={[f.pos.x, 0, f.pos.z]} rotation={[0, -f.dir + Math.PI / 2, 0]}>
      {[-1.5, 1.5].map((x) => (
        <group key={x}>
          <mesh position={[x, 1.7, 0]} castShadow>
            <cylinderGeometry args={[0.26, 0.34, 3.4, 10]} />
            <meshPhysicalMaterial {...glass} />
          </mesh>
          <mesh position={[x, 3.45, 0]}>
            <sphereGeometry args={[0.34, 12, 12]} />
            <meshPhysicalMaterial {...glass} />
          </mesh>
          <mesh position={[x, 0.12, 0]}>
            <cylinderGeometry args={[0.55, 0.65, 0.24, 10]} />
            <meshStandardMaterial color="#cfd8ea" roughness={0.6} metalness={0.3} />
          </mesh>
        </group>
      ))}
      <mesh position={[0, 3.65, 0]} rotation={[0, 0, Math.PI / 2]}>
        <capsuleGeometry args={[0.2, 2.6, 6, 12]} />
        <meshPhysicalMaterial {...glass} />
      </mesh>
      {[0, 1, 2].map((i) => (
        <mesh key={i} position={[0, 0.05, 0.9 + i * 0.7]} receiveShadow>
          <boxGeometry args={[2.6 - i * 0.4, 0.1, 0.6]} />
          <meshStandardMaterial color="#dde4f2" roughness={0.8} />
        </mesh>
      ))}
      {/* the dream itself (accent 1) */}
      <mesh position={[0, 1.85, 0]}>
        <planeGeometry args={[2.5, 3.2]} />
        <meshStandardMaterial ref={portal} color="#0b1a33" emissive="#7fd4ff"
          emissiveIntensity={1.8} transparent opacity={0.5} side={THREE.DoubleSide}
          depthWrite={false} />
      </mesh>
      {/* orbiting rune-orbs (accents 2 and 3) */}
      <group ref={orbs} position={[0, 2.4, 0]}>
        {[0, Math.PI].map((a) => (
          <mesh key={a} position={[Math.cos(a) * 1.9, 0, Math.sin(a) * 0.6]}>
            <sphereGeometry args={[0.13, 10, 10]} />
            <meshStandardMaterial color="#7fd4ff" emissive="#7fd4ff" emissiveIntensity={2.4} />
          </mesh>
        ))}
      </group>
      {/* unformed, undreamed land beyond the door */}
      <mesh position={[0, 0.01, -7]} rotation={[-Math.PI / 2, 0, 0]}>
        <circleGeometry args={[6.5, 26]} />
        <meshStandardMaterial color="#aab6c8" transparent opacity={0.22} roughness={1} />
      </mesh>
      <Html position={[0, 4.6, 0]} center distanceFactor={46} style={{ pointerEvents: "none" }}>
        <div className="gate-label">{f.name}</div>
      </Html>
    </group>
  );
}
