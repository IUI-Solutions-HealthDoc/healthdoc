"use client";

import { useEffect } from "react";

/**
 * Scrolling the page with the pointer over a focused number field changed
 * its value: a lab result or a dispense quantity moved up or down while the
 * user only meant to scroll (QA 12 Oct 2026). One listener for the whole app:
 * a wheel over the focused number input takes focus away first, so the page
 * scrolls and the value stays as typed.
 */
export function NumberWheelGuard() {
  useEffect(() => {
    const onWheel = (event: WheelEvent) => {
      const target = event.target;
      if (
        target instanceof HTMLInputElement &&
        target.type === "number" &&
        document.activeElement === target
      ) {
        target.blur();
      }
    };
    document.addEventListener("wheel", onWheel, { capture: true, passive: true });
    return () => document.removeEventListener("wheel", onWheel, { capture: true });
  }, []);
  return null;
}
