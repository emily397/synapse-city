/* Central "data-core" monument for the town square.
   Authored to the web3d-mcp synthesis contract (id a4890bd0..):
   12 primitive meshes, meshPhysicalMaterial chrome + 3 emissive accents,
   floating + rotating. Marks the heart of Synapse City. */
import { forwardRef, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";

const CHROME = { color: "#e8edf8", metalness: 1, roughness: 0.06, envMapIntensity: 1.6 };
function Chrome() { return <meshPhysicalMaterial {...(CHROME as any)} />; }
function Accent({ i = 2.2 }: { i?: number }) {
  return <meshStandardMaterial color="#dff4ff" emissive="#5cc8ff" emissiveIntensity={i}
    metalness={0.3} roughness={0.2} />;
}

export const Landmark = forwardRef<THREE.Group>((_props, ref) => {
  const crystal = useRef<THREE.Group>(null);
  const orbit = useRef<THREE.Group>(null);
  useFrame((state) => {
    const t = state.clock.elapsedTime;
    if (crystal.current) {
      crystal.current.rotation.y = t * 0.4;
      crystal.current.position.y = 3.0 + Math.sin(t * 0.8) * 0.22;
    }
    if (orbit.current) orbit.current.rotation.y = -t * 0.55;
  });

  return (
    <group ref={ref}>
      {/* base */}
      <mesh position={[0, 0.25, 0]} castShadow receiveShadow>
        <cylinderGeometry args={[1.15, 1.35, 0.5, 6]} /><Chrome />
      </mesh>
      <mesh position={[0, 0.52, 0]} rotation={[Math.PI / 2, 0, 0]}>
        <torusGeometry args={[1.18, 0.07, 12, 6]} /><Accent i={2.4} />
      </mesh>
      {[0, 1, 2].map((k) => (
        <mesh key={k} position={[Math.cos((k / 3) * Math.PI * 2) * 1.0, 0.9,
          Math.sin((k / 3) * Math.PI * 2) * 1.0]} rotation={[0, -(k / 3) * Math.PI * 2, 0.18]} castShadow>
          <cylinderGeometry args={[0.06, 0.06, 1.4, 6]} /><Chrome />
        </mesh>
      ))}

      {/* floating faceted crystal */}
      <group ref={crystal} position={[0, 3, 0]}>
        <mesh position={[0, 0.62, 0]} castShadow>
          <cylinderGeometry args={[0, 0.62, 1.25, 6]} /><Chrome />
        </mesh>
        <mesh position={[0, -0.62, 0]} castShadow>
          <cylinderGeometry args={[0.62, 0, 1.25, 6]} /><Chrome />
        </mesh>
        <mesh>
          <sphereGeometry args={[0.3, 20, 20]} /><Accent i={2.8} />
        </mesh>
        <mesh rotation={[Math.PI / 2.4, 0, 0]}>
          <torusGeometry args={[0.92, 0.045, 12, 32]} /><Accent i={2.0} />
        </mesh>
        <group ref={orbit}>
          {[0, 1, 2].map((k) => (
            <mesh key={k} position={[Math.cos((k / 3) * Math.PI * 2) * 1.25, 0,
              Math.sin((k / 3) * Math.PI * 2) * 1.25]} castShadow>
              <sphereGeometry args={[0.14, 12, 12]} /><Chrome />
            </mesh>
          ))}
        </group>
      </group>

      <pointLight position={[0, 3, 0]} color="#5cc8ff" intensity={6} distance={16} decay={2} />
    </group>
  );
});
