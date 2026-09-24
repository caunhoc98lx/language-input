"use client";

import { useEffect, useRef, useState } from "react";

/**
 * Counts down from `seconds` and fires `onExpire` exactly once when it hits 0.
 * Unmount (e.g. once the attempt is submitted) to stop/hide it - there's no
 * pause, since IELTS's own clock doesn't pause either.
 */
export default function Countdown({ seconds, onExpire }: { seconds: number; onExpire: () => void }) {
  const [remaining, setRemaining] = useState(seconds);
  const expiredRef = useRef(false);
  const onExpireRef = useRef(onExpire);

  useEffect(() => {
    onExpireRef.current = onExpire;
  }, [onExpire]);

  useEffect(() => {
    const id = setInterval(() => {
      setRemaining((r) => {
        if (r <= 1) {
          clearInterval(id);
          if (!expiredRef.current) {
            expiredRef.current = true;
            onExpireRef.current();
          }
          return 0;
        }
        return r - 1;
      });
    }, 1000);
    return () => clearInterval(id);
  }, []);

  const mins = Math.floor(remaining / 60);
  const secs = remaining % 60;

  return (
    <span className={`timer${remaining <= 60 ? " urgent" : ""}`}>
      ⏱ {mins}:{secs.toString().padStart(2, "0")}
    </span>
  );
}
