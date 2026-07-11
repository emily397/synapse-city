import { useRef } from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import { EffectComposer, Bloom, Vignette } from "@react-three/postprocessing";
import { useStore } from "../store";
import { City } from "./City";
import { Agents } from "./Agents";
import * as THREE from "three";

// Presenter mode: a slow cinematic camera that auto-frames wherever the latest
// conversation is happening. OrbitControls stays mounted (keeps the r3f frameloop
// healthy); in presenter mode we drive the camera and it is disabled for input.
function CameraDirector({ presenter, controls }: { presenter: boolean; controls: any }) {
  const focus = useStore((s) => s.focus);
  const { camera } = useThree();
  const tgt = useRef(new THREE.Vector3(0, 2, 0));
  const des = useRef(new THREE.Vector3(0, 26, 40));
  useFrame((state, dt) => {
    if (!presenter) return;
    const f = focus ?? { x: 0, z: 0 };
    const a = state.clock.elapsedTime * 0.12;
    des.current.set(f.x + Math.cos(a) * 30, 26, f.z + Math.sin(a) * 30);
    camera.position.lerp(des.current, Math.min(1, dt * 0.7));
    tgt.current.lerp(new THREE.Vector3(f.x, 2, f.z), Math.min(1, dt * 1.5));
    camera.lookAt(tgt.current);
    if (controls.current) controls.current.target.copy(tgt.current);
  });
  return null;
}

// Postprocessing (bloom/vignette) can fail on some headless/older GL stacks.
// Toggle off with ?flat in the URL if you ever see a blank canvas.
const POST = !new URLSearchParams(location.search).has("flat");

// Sky/ambience interpolated by time of day.
function palette(hour: number, night: boolean) {
  if (night) return { bg: "#070912", fog: "#0a0e1f", amb: 0.25, sun: 0.15 };
  if (hour < 8) return { bg: "#f7b267", fog: "#e8a15a", amb: 0.6, sun: 0.9 };   // dawn
  if (hour > 18) return { bg: "#b56576", fog: "#8a5a6d", amb: 0.5, sun: 0.7 };  // dusk
  return { bg: "#bfe3ff", fog: "#a9d4f5", amb: 0.85, sun: 1.15 };               // day
}

export function Scene() {
  const clock = useStore((s) => s.clock);
  const autoRotate = useStore((s) => s.autoRotate);
  const presenter = useStore((s) => s.presenter);
  const controls = useRef<any>(null);
  const p = palette(clock?.hour ?? 12, clock?.night ?? false);

  return (
    <Canvas shadows camera={{ position: [0, 48, 62], fov: 42 }}
            gl={{ antialias: true }} dpr={[1, 2]} resize={{ debounce: 0 }}
            style={{ position: "absolute", inset: 0, width: "100%", height: "100%" }}>
      <color attach="background" args={[p.bg]} />
      <fog attach="fog" args={[p.fog, 70, 190]} />
      <hemisphereLight intensity={p.amb} groundColor={"#20304a"} />
      <directionalLight
        position={[40, 70, 20]} intensity={p.sun} castShadow
        shadow-mapSize={[2048, 2048]}
        shadow-camera-left={-70} shadow-camera-right={70}
        shadow-camera-top={70} shadow-camera-bottom={-70} />
      <City />
      <Agents />
      <OrbitControls
        ref={controls}
        enabled={!presenter}
        autoRotate={!presenter && autoRotate} autoRotateSpeed={0.5}
        enablePan enableDamping dampingFactor={0.08}
        minDistance={25} maxDistance={130}
        maxPolarAngle={Math.PI / 2.15} target={[0, 2, 0]} />
      <CameraDirector presenter={presenter} controls={controls} />
      {POST && (
        <EffectComposer>
          <Bloom intensity={0.5} luminanceThreshold={0.75} luminanceSmoothing={0.25}
                 mipmapBlur />
          <Vignette eskil={false} offset={0.2} darkness={0.55} />
        </EffectComposer>
      )}
    </Canvas>
  );
}

// silence unused import in some TS configs
void THREE;
