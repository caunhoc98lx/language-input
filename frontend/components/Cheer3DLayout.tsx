"use client";
/**
 * Cheer3DLayout - two 3D cheerleaders (Lumi & Mira) in the empty space to
 * the left and right of the quiz card, reacting to `mood`.
 *
 * Under 1200px (or before hydration) no characters render and the grid is a
 * single column, so the page looks exactly as it does without this wrapper.
 * The WebGL part is loaded with next/dynamic (ssr: false) only once the
 * screen is wide enough - three.js never ships to phones.
 */
import { useCallback, useSyncExternalStore, type ReactNode } from "react";
import dynamic from "next/dynamic";
import type { CheerMood, CheerWho } from "./Cheer3DCharacter";

export type { CheerMood, CheerWho };

const Cheer3DCharacter = dynamic(() => import("./Cheer3DCharacter"), { ssr: false });

/** false on the server and during hydration, then the live media-query value. */
function useMedia(query: string): boolean {
  const subscribe = useCallback((onChange: () => void) => {
    const mq = window.matchMedia(query);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [query]);
  return useSyncExternalStore(subscribe, () => window.matchMedia(query).matches, () => false);
}

export default function Cheer3DLayout({ children, mood = "idle", left = "lumi", right = "mira" }: {
  children: ReactNode; mood?: CheerMood; left?: CheerWho; right?: CheerWho;
}) {
  const wide = useMedia("(min-width: 1200px)");
  const calm = useMedia("(prefers-reduced-motion: reduce)");

  return (
    <div className="cheer3d-layout">
      {wide ? <Cheer3DCharacter who={left} mood={mood} facing={0.35} calm={calm} /> : <span />}
      <div className="cheer3d-layout__center">{children}</div>
      {wide ? <Cheer3DCharacter who={right} mood={mood} facing={-0.35} calm={calm} /> : <span />}
    </div>
  );
}
