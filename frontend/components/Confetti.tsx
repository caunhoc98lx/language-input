"use client";

const COLORS = ["#4f46e5", "#16a34a", "#d97706", "#dc2626", "#0ea5e9", "#db2777"];

export type ConfettiPiece = {
  id: number;
  left: number;
  color: string;
  delay: number;
  duration: number;
  rotation: number;
  drift: number;
};

/** Random generation belongs in the event handler that triggers the celebration,
 * not in this component's render - keeps Confetti itself pure. */
export function makeConfettiPieces(count = 60): ConfettiPiece[] {
  return Array.from({ length: count }, (_, i) => ({
    id: i,
    left: Math.random() * 100,
    color: COLORS[i % COLORS.length],
    delay: Math.random() * 0.15,
    duration: 1.1 + Math.random() * 0.8,
    rotation: Math.random() * 360,
    drift: (Math.random() - 0.5) * 120,
  }));
}

/** Fixed-position confetti burst. Pieces fall and fade out on their own via
 * CSS animation-fill-mode, so nothing needs to clear them afterwards - the
 * caller unmounts this along with the question. */
export default function Confetti({ pieces }: { pieces: ConfettiPiece[] | null }) {
  if (!pieces || pieces.length === 0) return null;

  return (
    <div className="confetti-layer" aria-hidden="true">
      {pieces.map((p) => (
        <span
          key={p.id}
          className="confetti-piece"
          style={
            {
              left: `${p.left}%`,
              background: p.color,
              animationDelay: `${p.delay}s`,
              animationDuration: `${p.duration}s`,
              "--drift": `${p.drift}px`,
              "--rot": `${p.rotation}deg`,
            } as React.CSSProperties
          }
        />
      ))}
    </div>
  );
}
