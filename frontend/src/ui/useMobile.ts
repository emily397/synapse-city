import { useEffect, useState } from "react";

const QUERY = "(max-width: 720px)";

// Snapshot at load: used for GPU decisions that can't change after the Canvas
// is created (shadows, postprocessing).
export const MOBILE_AT_LOAD =
  typeof window !== "undefined" && window.matchMedia(QUERY).matches;

// Reactive: used for DOM-level choices (speech bubbles, layout) that should
// follow rotation/resize.
export function useMobile(): boolean {
  const [m, setM] = useState(MOBILE_AT_LOAD);
  useEffect(() => {
    const mq = window.matchMedia(QUERY);
    const fn = (e: MediaQueryListEvent) => setM(e.matches);
    mq.addEventListener("change", fn);
    return () => mq.removeEventListener("change", fn);
  }, []);
  return m;
}
