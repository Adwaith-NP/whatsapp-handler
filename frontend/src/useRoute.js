import { useEffect, useState } from "react";

/**
 * Minimal URL routing: the current page lives in the address bar, so a refresh
 * (or a bookmark, or the back button) lands where you were instead of resetting
 * to the first page.
 *
 * nginx already serves index.html for unknown paths, so real URLs work without
 * a hash. Three pages don't justify pulling in a router library.
 */
export function useRoute() {
  const [path, setPath] = useState(() => window.location.pathname);

  useEffect(() => {
    const onPop = () => setPath(window.location.pathname);
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  function navigate(to, { replace = false } = {}) {
    if (to === window.location.pathname) return;
    window.history[replace ? "replaceState" : "pushState"]({}, "", to);
    setPath(to);
  }

  return [path, navigate];
}
