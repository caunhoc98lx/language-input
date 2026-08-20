"use client";

import { useEffect } from "react";

/** Registers the offline shell. Silent if the browser has no support. */
export default function ServiceWorker() {
  useEffect(() => {
    if (process.env.NODE_ENV !== "production") return;
    if (!("serviceWorker" in navigator)) return;
    navigator.serviceWorker.register("/sw.js").catch(() => {
      /* offline support is a bonus, never a failure the learner should see */
    });
  }, []);
  return null;
}
