"use client";
/**
 * Cheer3DLayout - two illustrated cheerleaders in the empty space to the left
 * and right of the quiz card, reacting to `mood` with CSS animations.
 *
 * Under 1200px the side columns are hidden by CSS and the grid collapses to a
 * single column, so the page looks exactly as it does without this wrapper.
 */
import { useState, type ReactNode } from "react";
import Image from "next/image";

export type CheerMood = "idle" | "correct" | "wrong" | "streak";
export type CheerWho = "lumi" | "mira" | "luna";

// ponytail: lumi has no art yet and reuses luna mirrored. Drop
// /characters/<who>.png into public/ and point `src` at it to give it its own.
const ART: Record<CheerWho, { src: string; w: number; h: number; flip?: boolean }> = {
  luna: { src: "/characters/luna.png", w: 800, h: 1062 },
  mira: { src: "/characters/mira.png", w: 800, h: 800 },
  lumi: { src: "/characters/luna.png", w: 800, h: 1062, flip: true },
};

const LINES: Record<CheerWho, Record<CheerMood, string>> = {
  lumi: {
    idle: "Cố lên, bạn làm được mà!",
    correct: "Giỏi quá! 🎉",
    streak: "Combo đỉnh luôn! 🔥",
    wrong: "Không sao, câu sau nhé!",
  },
  mira: {
    idle: "Nghĩ xem từ này hợp với ngữ cảnh nào nhé 💭",
    correct: "Dùng từ tự nhiên quá, như người bản xứ luôn!",
    streak: "Phong độ này thì band 7 trong tầm tay rồi 💎",
    wrong: "Hơi tiếc chút thôi, lần sau chắc chắn nhớ 🤍",
  },
  luna: {
    idle: "Mình đang ở đây cùng bạn cố gắng 🌸",
    correct: "Đúng rồi! Bạn giỏi hơn bạn nghĩ đó ✨",
    streak: "Liên tiếp luôn, mình tự hào về bạn lắm 🥰",
    wrong: "Không sao đâu, sai một lần là nhớ cả đời 💕",
  },
};

function Cheerleader({ who, mood, said }: { who: CheerWho; mood: CheerMood; said: CheerMood }) {
  const art = ART[who];
  return (
    <aside className="cheer3d" aria-hidden="true">
      <div key={said} className="cheer3d__bubble">{LINES[who][said]}</div>
      {/* key={mood} restarts the reaction animation on every answer */}
      <div key={`p-${mood}`} className={`cheer-portrait cheer-portrait--${mood}`}>
        <Image
          src={art.src} alt="" width={art.w} height={art.h} sizes="320px" quality={90}
          style={art.flip ? { transform: "scaleX(-1)" } : undefined}
        />
      </div>
    </aside>
  );
}

export default function Cheer3DLayout({ children, mood = "idle", left = "lumi", right = "mira" }: {
  children: ReactNode; mood?: CheerMood; left?: CheerWho; right?: CheerWho;
}) {
  // `mood` falls back to idle after a moment (that drives the portrait
  // animation); the bubble keeps the last answer's line until the next answer
  // changes it, e.g. the "wrong" line stays up until a correct answer.
  const [said, setSaid] = useState<CheerMood>("idle");
  if (mood !== "idle" && mood !== said) setSaid(mood);

  return (
    <div className="cheer3d-layout">
      <Cheerleader who={left} mood={mood} said={said} />
      <div className="cheer3d-layout__center">{children}</div>
      <Cheerleader who={right} mood={mood} said={said} />
    </div>
  );
}
