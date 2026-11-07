"use client";
import { useEffect, useState } from "react";
const views = new Set([
  "overview",
  "memories",
  "agents",
  "permissions",
  "teams",
  "vault",
  "activity",
  "workbench",
  "demo",
  "settings",
]);
export function useWorkspaceNavigation() {
  const [view, updateView] = useState("overview");
  useEffect(() => {
    const restore = () => {
      const value = window.location.hash.slice(1);
      updateView(views.has(value) ? value : "overview");
    };
    restore();
    window.addEventListener("popstate", restore);
    window.addEventListener("hashchange", restore);
    return () => {
      window.removeEventListener("popstate", restore);
      window.removeEventListener("hashchange", restore);
    };
  }, []);
  function navigate(next) {
    if (!views.has(next)) return;
    if (next !== view) window.history.pushState(null, "", `#${next}`);
    updateView(next);
    window.requestAnimationFrame(() => {
      document
        .querySelector(".workspace-heading h1")
        ?.focus({ preventScroll: true });
      window.scrollTo({ top: 0, behavior: "instant" });
    });
  }
  return [view, navigate];
}
