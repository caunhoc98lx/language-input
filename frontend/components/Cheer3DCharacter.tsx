"use client";
/**
 * One 3D cheerleader (Lumi or Mira) with a speech bubble. WebGL-only code
 * lives here so Cheer3DLayout can load it lazily (next/dynamic, ssr: false):
 * screens under 1200px never download three.js at all.
 *
 * Moods:
 *   idle    -> smile, blink, gentle sway
 *   correct -> ^^ eyes, open mouth, jumping, pom-poms up, sparkles
 *   streak  -> star eyes, faster jumps, body spin, alternating pom-poms
 *   wrong   -> worried brows, "o" mouth, sweat drop, one fist raised
 */
import { createContext, useContext, useMemo, useRef, type ReactNode, type RefObject } from "react";
import { Canvas, useFrame, type ThreeElements } from "@react-three/fiber";
import { ContactShadows, Outlines, Sparkles } from "@react-three/drei";
import * as THREE from "three";

export type CheerMood = "idle" | "correct" | "wrong" | "streak";
export type CheerWho = "lumi" | "mira" | "luna";

const INK = "#2B2238";

type Look = {
  hair: string; top: string; skirt: string; legs: string; eye: string;
  accent: string; pom: string; skin: string; style: "twintails" | "ponytail" | "long"; phase: number;
  /** Luna: floor-length gown with gold trim, moon orbs instead of pom-poms. */
  gown?: boolean;
  flower?: string; // flower hairpin colour (replaces the star clip)
  gem?: string; // circlet / chest / earring gem colour
  lashes?: boolean;
};

const CHARACTERS: Record<CheerWho, Look> = {
  lumi: {
    hair: "#2E2640", top: "#4F46E5", skirt: "#312E81", legs: "#1E1B3A",
    eye: "#6366F1", accent: "#FACC15", pom: "#FACC15", skin: "#FFE2D1",
    style: "twintails", phase: 0,
  },
  mira: {
    hair: "#8A4B3A", top: "#EC4899", skirt: "#9D174D", legs: "#3B1A2A",
    eye: "#14B8A6", accent: "#FFFFFF", pom: "#F9A8D4", skin: "#FFE6D6",
    style: "ponytail", phase: 1.3,
  },
  luna: {
    hair: "#2A1F3D", top: "#FAF7FF", skirt: "#C4B5FD", legs: "#2A1F3D",
    eye: "#8B5CF6", accent: "#D4A73C", pom: "#EDE9FE", skin: "#FFEDE4",
    style: "long", phase: 0.7, gown: true, flower: "#C4A3F5", gem: "#8B5CF6", lashes: true,
  },
};

const LINES: Record<CheerWho, Record<CheerMood, string>> = {
  lumi: {
    idle: "Cố lên, bạn làm được mà!",
    correct: "Giỏi quá! 🎉",
    streak: "Combo đỉnh luôn! 🔥",
    wrong: "Không sao, câu sau nhé!",
  },
  mira: {
    idle: "Đọc kỹ rồi chọn nhé ✨",
    correct: "Chuẩn không cần chỉnh!",
    streak: "Đừng dừng lại nha!",
    wrong: "Sai là để nhớ lâu hơn 💪",
  },
  luna: {
    idle: "Ánh trăng soi lối cho bạn 🌙",
    correct: "Sáng như trăng rằm!",
    streak: "Trăng rực rỡ vì bạn đó ✨",
    wrong: "Trăng cũng có lúc khuyết, thử lại nhé",
  },
};

/* ---------- toon (anime-style) material ---------- */

const GradientCtx = createContext<THREE.Texture | null>(null);

function useToonGradient(): THREE.DataTexture {
  return useMemo(() => {
    const tex = new THREE.DataTexture(new Uint8Array([110, 190, 255]), 3, 1, THREE.RedFormat);
    tex.minFilter = THREE.NearestFilter;
    tex.magFilter = THREE.NearestFilter;
    tex.needsUpdate = true;
    return tex;
  }, []);
}

function Toon({ color }: { color: string }) {
  const gradientMap = useContext(GradientCtx);
  return <meshToonMaterial color={color} gradientMap={gradientMap} />;
}

type PartProps = Omit<ThreeElements["mesh"], "children"> & { children: ReactNode; color: string; outline?: number };

/** A mesh with an anime-style ink outline. */
function Part({ children, color, outline = 0.016, ...props }: PartProps) {
  return (
    <mesh {...props}>
      {children}
      <Toon color={color} />
      {outline > 0 && <Outlines thickness={outline} color={INK} />}
    </mesh>
  );
}

function useStarGeometry(r = 0.07): THREE.ExtrudeGeometry {
  return useMemo(() => {
    const s = new THREE.Shape();
    for (let i = 0; i < 10; i++) {
      const a = (i / 10) * Math.PI * 2 + Math.PI / 2;
      const rr = i % 2 ? r * 0.45 : r;
      const x = Math.cos(a) * rr;
      const y = Math.sin(a) * rr;
      if (i === 0) s.moveTo(x, y);
      else s.lineTo(x, y);
    }
    s.closePath();
    return new THREE.ExtrudeGeometry(s, { depth: 0.02, bevelEnabled: false });
  }, [r]);
}

/* ---------- face ---------- */

// Place a detail on the head's surface (sphere, radius 0.5), turned along its normal.
function onFace(x: number, y: number, lift = 0): { position: [number, number, number]; rotation: [number, number, number] } {
  const z = Math.sqrt(Math.max(0, 0.25 - x * x - y * y)) + lift;
  return { position: [x, y, z], rotation: [-Math.atan2(y, z), Math.atan2(x, z), 0] };
}

type EyeType = "normal" | "happy" | "star";

function Eye({ x, color, type, star, lashes }: { x: number; color: string; type: EyeType; star: THREE.BufferGeometry; lashes?: boolean }) {
  return (
    <group {...onFace(x, 0, 0.002)}>
      {type === "normal" && (
        <>
          {lashes && (
            // upper lash line, flicked outward at the corner
            <mesh position={[x > 0 ? 0.008 : -0.008, 0.045, 0.012]} rotation={[0, 0, x > 0 ? -0.25 : 0.25]} scale={[1.15, 0.9, 0.3]}>
              <torusGeometry args={[0.062, 0.012, 6, 18, Math.PI]} />
              <meshBasicMaterial color={INK} />
            </mesh>
          )}
          <mesh scale={[0.8, 1.2, 0.35]}>
            <sphereGeometry args={[0.075, 20, 20]} />
            <meshBasicMaterial color={INK} />
          </mesh>
          <mesh position={[0, -0.025, 0.02]} scale={[0.6, 0.6, 0.3]}>
            <sphereGeometry args={[0.07, 16, 16]} />
            <meshBasicMaterial color={color} />
          </mesh>
          <mesh position={[0.022, 0.035, 0.03]}>
            <sphereGeometry args={[0.02, 10, 10]} />
            <meshBasicMaterial color="#ffffff" />
          </mesh>
        </>
      )}
      {type === "happy" && (
        <mesh>
          <torusGeometry args={[0.055, 0.016, 8, 24, Math.PI]} />
          <meshBasicMaterial color={INK} />
        </mesh>
      )}
      {type === "star" && (
        <mesh geometry={star} position={[0, 0, -0.01]}>
          <meshBasicMaterial color="#FACC15" />
          <Outlines thickness={0.01} color={INK} />
        </mesh>
      )}
    </group>
  );
}

function Mouth({ mood }: { mood: CheerMood }) {
  return (
    <group {...onFace(0, -0.2, 0.002)}>
      {mood === "idle" && (
        <mesh rotation={[0, 0, Math.PI]}>
          <torusGeometry args={[0.055, 0.013, 8, 24, Math.PI]} />
          <meshBasicMaterial color="#9F1239" />
        </mesh>
      )}
      {(mood === "correct" || mood === "streak") && (
        <>
          <mesh scale={[1, 0.8, 0.3]}>
            <sphereGeometry args={[0.07, 20, 20]} />
            <meshBasicMaterial color="#9F1239" />
          </mesh>
          <mesh position={[0, -0.025, 0.012]} scale={[1, 0.6, 0.3]}>
            <sphereGeometry args={[0.035, 16, 16]} />
            <meshBasicMaterial color="#FB7185" />
          </mesh>
        </>
      )}
      {mood === "wrong" && (
        <mesh>
          <torusGeometry args={[0.026, 0.011, 8, 20]} />
          <meshBasicMaterial color="#9F1239" />
        </mesh>
      )}
    </group>
  );
}

/* ---------- character ---------- */

type SceneProps = { who: CheerWho; mood: CheerMood; facing: number; calm: boolean };

function Character({ who, mood, facing, calm }: SceneProps) {
  const c = CHARACTERS[who];
  const star = useStarGeometry(0.075);
  const badge = useStarGeometry(0.06);

  const root = useRef<THREE.Group>(null);
  const head = useRef<THREE.Group>(null);
  const armL = useRef<THREE.Group>(null);
  const armR = useRef<THREE.Group>(null);
  const eyes = useRef<THREE.Group>(null);
  const browL = useRef<THREE.Group>(null);
  const browR = useRef<THREE.Group>(null);
  const hair = useRef<THREE.Group>(null);
  const blink = useRef({ wait: 2, t: 0 });

  const eyeType: EyeType = mood === "correct" ? "happy" : mood === "streak" ? "star" : "normal";
  const blushOpacity = mood === "correct" || mood === "streak" ? 0.85 : 0.5;

  useFrame((state, dt) => {
    if (!root.current || !head.current || !armL.current || !armR.current ||
        !eyes.current || !browL.current || !browR.current || !hair.current) return;
    const t = state.clock.elapsedTime + c.phase;
    const k = calm ? 0.2 : 1;
    const damp = THREE.MathUtils.damp;

    let y = Math.sin(t * 2) * 0.03 * k;
    let spin = 0;
    let headX = 0;
    let headZ = Math.sin(t * 1.2) * 0.06 * k;
    let armLeft = 0.3 + Math.sin(t * 2) * 0.08 * k;
    let armRight = 0.3 + Math.sin(t * 2 + 1) * 0.08 * k;
    let worried = 0;
    let browLift = 0;
    let sway = Math.sin(t * 2) * 0.06 * k;

    if (mood === "correct") {
      y = Math.abs(Math.sin(t * 6)) * 0.22 * k;
      armLeft = armRight = 2.5 + Math.sin(t * 12) * 0.25 * k;
      headZ = Math.sin(t * 6) * 0.12 * k;
      browLift = 0.03;
      sway = Math.sin(t * 6) * 0.25 * k;
    } else if (mood === "streak") {
      y = Math.abs(Math.sin(t * 8)) * 0.28 * k;
      spin = Math.sin(t * 4) * 0.5 * k;
      armLeft = 2.2 + Math.sin(t * 10) * 0.6 * k;
      armRight = 2.2 - Math.sin(t * 10) * 0.6 * k;
      browLift = 0.035;
      sway = Math.sin(t * 8) * 0.3 * k;
    } else if (mood === "wrong") {
      y = Math.sin(t * 2) * 0.015 * k;
      headX = 0.12;
      headZ = 0.1;
      armLeft = 0.15;
      armRight = 1.3 + Math.sin(t * 5) * 0.3 * k; // "you got this!" fist
      worried = 0.35;
      sway = Math.sin(t * 1.5) * 0.04 * k;
    }

    root.current.position.y = damp(root.current.position.y, y, 14, dt);
    root.current.rotation.y = damp(root.current.rotation.y, facing + spin, 6, dt);
    head.current.rotation.x = damp(head.current.rotation.x, headX, 6, dt);
    head.current.rotation.z = damp(head.current.rotation.z, headZ, 6, dt);
    armL.current.rotation.z = damp(armL.current.rotation.z, -armLeft, 10, dt);
    armR.current.rotation.z = damp(armR.current.rotation.z, armRight, 10, dt);
    browL.current.rotation.z = damp(browL.current.rotation.z, worried, 10, dt);
    browR.current.rotation.z = damp(browR.current.rotation.z, -worried, 10, dt);
    browL.current.position.y = damp(browL.current.position.y, 0.12 + browLift, 10, dt);
    browR.current.position.y = browL.current.position.y;
    hair.current.rotation.z = damp(hair.current.rotation.z, sway, 8, dt);

    // random blinking
    const b = blink.current;
    b.wait -= dt;
    let open = 1;
    if (b.wait < 0) {
      b.t += dt;
      open = 0.1;
      if (b.t > 0.12) {
        b.wait = 2 + Math.random() * 3;
        b.t = 0;
      }
    }
    eyes.current.scale.y = open;
  });

  const bangs = [-0.32, -0.16, 0, 0.16, 0.32];
  const arms: [number, RefObject<THREE.Group | null>][] = [[-1, armL], [1, armR]];

  return (
    <group ref={root} rotation={[0, facing, 0]}>
      {c.gown ? (
        <>
          {/* floor-length lavender gown with gold hem + belt */}
          <Part color={c.skirt} position={[0, 0.46, 0]}>
            <cylinderGeometry args={[0.25, 0.52, 0.8, 28]} />
          </Part>
          <Part color={c.accent} position={[0, 0.07, 0]} rotation={[Math.PI / 2, 0, 0]} outline={0.008}>
            <torusGeometry args={[0.515, 0.025, 8, 36]} />
          </Part>
          <Part color={c.accent} position={[0, 0.86, 0]} rotation={[Math.PI / 2, 0, 0]} outline={0.008}>
            <torusGeometry args={[0.27, 0.03, 8, 28]} />
          </Part>
        </>
      ) : (
        <>
          {/* legs + shoes */}
          {[-1, 1].map((s) => (
            <group key={s}>
              <Part color={c.legs} position={[s * 0.12, 0.33, 0]}>
                <capsuleGeometry args={[0.085, 0.3, 6, 12]} />
              </Part>
              <Part color="#FFFFFF" position={[s * 0.12, 0.08, 0.05]} scale={[1, 0.6, 1.4]}>
                <sphereGeometry args={[0.1, 16, 16]} />
              </Part>
            </group>
          ))}
          <Part color={c.skirt} position={[0, 0.68, 0]}>
            <cylinderGeometry args={[0.26, 0.42, 0.3, 24]} />
          </Part>
        </>
      )}

      {/* top (+ neckline) */}
      <Part color={c.top} position={[0, 1.06, 0]}>
        <capsuleGeometry args={[0.27, 0.28, 8, 20]} />
      </Part>
      <Part color={c.gown ? c.accent : "#FFFFFF"} position={[0, 1.42, 0]} rotation={[Math.PI / 2, 0, 0]} outline={0.01}>
        <torusGeometry args={[0.13, c.gown ? 0.03 : 0.04, 10, 24]} />
      </Part>
      {c.gem ? (
        // gold-set gem at the chest, like the pendant in the reference
        <group position={[0, 1.2, 0.265]}>
          <Part color={c.accent} outline={0.008}>
            <torusGeometry args={[0.055, 0.015, 8, 20]} />
          </Part>
          <mesh scale={[1, 1.3, 0.6]}>
            <octahedronGeometry args={[0.045]} />
            <Toon color={c.gem} />
          </mesh>
        </group>
      ) : (
        <mesh geometry={badge} position={[0.12, 1.15, 0.265]}>
          <Toon color={c.accent} />
          <Outlines thickness={0.008} color={INK} />
        </mesh>
      )}
      <Part color={c.skin} position={[0, 1.5, 0]} outline={0}>
        <cylinderGeometry args={[0.08, 0.08, 0.15, 12]} />
      </Part>

      {/* arms + pom-poms (pivot at the shoulder) */}
      {arms.map(([s, ref]) => (
        <group key={s} ref={ref} position={[s * 0.3, 1.3, 0]}>
          <Part color={c.top} position={[0, -0.26, 0]}>
            <capsuleGeometry args={[0.08, 0.32, 6, 12]} />
          </Part>
          <Part color={c.skin} position={[0, -0.52, 0]}>
            <sphereGeometry args={[0.085, 14, 14]} />
          </Part>
          {c.gown ? (
            // a small glowing moon orb instead of a pom-pom
            <mesh position={[0, -0.63, 0.02]}>
              <sphereGeometry args={[0.1, 20, 20]} />
              <meshBasicMaterial color={c.pom} />
              <Outlines thickness={0.01} color={c.flower ?? INK} />
            </mesh>
          ) : (
            <Part color={c.pom} position={[0, -0.64, 0]} outline={0.012}>
              <icosahedronGeometry args={[0.17, 1]} />
            </Part>
          )}
        </group>
      ))}

      {/* head */}
      <group ref={head} position={[0, 1.95, 0]}>
        <Part color={c.skin}>
          <sphereGeometry args={[0.5, 32, 32]} />
        </Part>

        {/* hair: back, bangs, side locks */}
        <Part color={c.hair} position={[0, 0.08, -0.1]}>
          <sphereGeometry args={[0.54, 32, 32]} />
        </Part>
        {bangs.map((x) => (
          <Part
            key={x}
            color={c.hair}
            position={[x, 0.33, Math.sqrt(0.26 - x * x - 0.33 * 0.33)]}
            scale={[1, 0.7, 0.7]}
            outline={0.012}
          >
            <sphereGeometry args={[0.19, 16, 16]} />
          </Part>
        ))}
        {[-1, 1].map((s) => (
          <Part key={s} color={c.hair} position={[s * 0.46, -0.12, 0.12]} outline={0.012}>
            <capsuleGeometry args={[0.07, 0.3, 6, 12]} />
          </Part>
        ))}

        {/* signature hairstyle - sways with the bounce */}
        <group ref={hair}>
          {c.style === "twintails" &&
            [-1, 1].map((s) => (
              <group key={s} position={[s * 0.5, 0.22, -0.12]}>
                <Part color={c.accent}>
                  <sphereGeometry args={[0.07, 12, 12]} />
                </Part>
                <Part color={c.hair} position={[s * 0.09, -0.38, -0.02]} rotation={[0, 0, s * 0.22]}>
                  <capsuleGeometry args={[0.13, 0.55, 8, 16]} />
                </Part>
              </group>
            ))}
          {c.style === "long" && (
            <>
              {/* waist-length hair down the back */}
              <Part color={c.hair} position={[0, -0.72, -0.3]} scale={[1, 1, 0.45]}>
                <capsuleGeometry args={[0.42, 0.95, 8, 20]} />
              </Part>
              {/* long locks falling in front of the shoulders */}
              {[-1, 1].map((s) => (
                <Part key={s} color={c.hair} position={[s * 0.42, -0.62, 0.14]} rotation={[0.12, 0, s * 0.1]} outline={0.012}>
                  <capsuleGeometry args={[0.075, 0.85, 6, 12]} />
                </Part>
              ))}
            </>
          )}
          {c.style === "ponytail" && (
            <group position={[0, 0.3, -0.42]}>
              <Part color={c.accent}>
                <sphereGeometry args={[0.08, 12, 12]} />
              </Part>
              <Part color={c.hair} position={[0, -0.38, -0.14]} rotation={[0.35, 0, 0]}>
                <capsuleGeometry args={[0.14, 0.55, 8, 16]} />
              </Part>
            </group>
          )}
        </group>

        {c.flower ? (
          <>
            {/* flower hairpin: five petals around a gold centre */}
            <group {...onFace(0.33, 0.27, 0.13)} scale={1.35}>
              {[0, 1, 2, 3, 4].map((i) => {
                const a = (i / 5) * Math.PI * 2;
                return (
                  <Part key={i} color={c.flower!} position={[Math.cos(a) * 0.06, Math.sin(a) * 0.06, 0]} scale={[1, 1, 0.45]} outline={0.008}>
                    <sphereGeometry args={[0.05, 12, 12]} />
                  </Part>
                );
              })}
              <Part color={c.accent} position={[0, 0, 0.02]} outline={0.006}>
                <sphereGeometry args={[0.03, 10, 10]} />
              </Part>
            </group>
            {/* circlet gem on the forehead */}
            <mesh {...onFace(0, 0.2, 0.01)} scale={[0.8, 1.2, 0.5]}>
              <octahedronGeometry args={[0.03]} />
              <Toon color={c.gem ?? c.accent} />
              <Outlines thickness={0.006} color={c.accent} />
            </mesh>
            {/* drop earrings */}
            {[-1, 1].map((s) => (
              <group key={s} position={[s * 0.5, -0.2, 0.02]}>
                <mesh>
                  <sphereGeometry args={[0.022, 10, 10]} />
                  <Toon color={c.accent} />
                </mesh>
                <mesh position={[0, -0.07, 0]} scale={[0.8, 1.3, 0.8]}>
                  <octahedronGeometry args={[0.03]} />
                  <Toon color={c.gem ?? c.accent} />
                </mesh>
              </group>
            ))}
          </>
        ) : (
          /* star hair clip */
          <mesh geometry={star} {...onFace(0.3, 0.3, 0.12)}>
            <Toon color={who === "lumi" ? "#FACC15" : "#FFFFFF"} />
            <Outlines thickness={0.01} color={INK} />
          </mesh>
        )}

        {/* expression */}
        <group ref={eyes}>
          <Eye x={-0.18} color={c.eye} type={eyeType} star={star} lashes={c.lashes} />
          <Eye x={0.18} color={c.eye} type={eyeType} star={star} lashes={c.lashes} />
        </group>
        <group ref={browL} position={[-0.18, 0.12, 0.45]}>
          <mesh rotation={[0, 0, Math.PI / 2]}>
            <capsuleGeometry args={[0.013, 0.07, 4, 8]} />
            <meshBasicMaterial color={INK} />
          </mesh>
        </group>
        <group ref={browR} position={[0.18, 0.12, 0.45]}>
          <mesh rotation={[0, 0, Math.PI / 2]}>
            <capsuleGeometry args={[0.013, 0.07, 4, 8]} />
            <meshBasicMaterial color={INK} />
          </mesh>
        </group>
        {[-1, 1].map((s) => (
          <mesh key={s} {...onFace(s * 0.3, -0.12)} scale={[1, 0.55, 0.2]}>
            <sphereGeometry args={[0.075, 16, 16]} />
            <meshBasicMaterial color="#F9A8B8" transparent opacity={blushOpacity} />
          </mesh>
        ))}
        <Mouth mood={mood} />
        {mood === "wrong" && (
          <mesh position={[0.4, 0.22, 0.27]} scale={[0.7, 1, 0.5]}>
            <sphereGeometry args={[0.06, 16, 16]} />
            <Toon color="#7DD3FC" />
            <Outlines thickness={0.008} color={INK} />
          </mesh>
        )}
      </group>
    </group>
  );
}

/** Full moon behind Luna: pale disc, soft halo, a few maria. Static - it
 * lives in the scene, not on the character, so it doesn't bounce with her. */
function Moon({ glow }: { glow: boolean }) {
  const maria: [number, number, number][] = [[-0.3, 0.25, 0.22], [0.25, 0.35, 0.14], [0.1, -0.2, 0.26], [-0.35, -0.3, 0.12], [0.45, -0.05, 0.1]];
  return (
    <group position={[0, 2.05, -1.8]}>
      <mesh position={[0, 0, -0.01]}>
        <circleGeometry args={[1.25, 48]} />
        <meshBasicMaterial color="#DDD6FE" transparent opacity={glow ? 0.6 : 0.35} toneMapped={false} />
      </mesh>
      <mesh>
        <circleGeometry args={[1.02, 48]} />
        <meshBasicMaterial color="#FBFAFF" toneMapped={false} />
      </mesh>
      {maria.map(([x, y, r]) => (
        <mesh key={`${x}${y}`} position={[x, y, 0.005]}>
          <circleGeometry args={[r, 24]} />
          <meshBasicMaterial color="#E4DEF7" toneMapped={false} />
        </mesh>
      ))}
    </group>
  );
}

function Scene({ who, mood, facing, calm }: SceneProps) {
  const gradient = useToonGradient();
  const celebrating = mood === "correct" || mood === "streak";
  return (
    <GradientCtx.Provider value={gradient}>
      <ambientLight intensity={1.1} />
      <directionalLight position={[2.5, 4, 3]} intensity={1.8} />
      {CHARACTERS[who].gown && <Moon glow={celebrating} />}
      <Character who={who} mood={mood} facing={facing} calm={calm} />
      <ContactShadows position={[0, 0.001, 0]} opacity={0.3} scale={3} blur={2.4} far={1.2} />
      {celebrating && (
        <Sparkles
          count={mood === "streak" ? 40 : 22}
          scale={[2.2, 2.6, 1.2]}
          position={[0, 1.4, 0]}
          size={5}
          speed={0.8}
          color={CHARACTERS[who].flower ?? CHARACTERS[who].pom}
        />
      )}
    </GradientCtx.Provider>
  );
}

export default function Cheer3DCharacter({ who, mood, facing, calm }: SceneProps) {
  return (
    <aside className="cheer3d" aria-hidden="true">
      <div key={mood} className="cheer3d__bubble">
        {LINES[who][mood]}
      </div>
      <div className="cheer3d__stage">
        {/* rotation given explicitly: without it R3F aims the camera at the
            origin (the feet), which tilts the view down and crops the head */}
        <Canvas dpr={[1, 2]} camera={{ position: [0, 1.3, 5.6], rotation: [0, 0, 0], fov: 32 }} gl={{ antialias: true, alpha: true }}>
          <Scene who={who} mood={mood} facing={facing} calm={calm} />
        </Canvas>
      </div>
    </aside>
  );
}
