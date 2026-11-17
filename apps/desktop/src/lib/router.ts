import { useCallback, useEffect, useState } from "react";

/** 极简 hash 路由：Tauri WebView 内无需引入完整路由库。 */
export type Route =
  | { name: "home" }
  | { name: "editor"; recipeId: string | null };

export function parseRoute(hash: string): Route {
  const raw = hash.replace(/^#/, "");
  const path = raw.split("?")[0] ?? "";
  const match = /^\/editor(?:\/([^/]+))?\/?$/.exec(path);
  if (match) {
    const id = match[1] ? decodeURIComponent(match[1]) : null;
    return { name: "editor", recipeId: id && id.trim() ? id : null };
  }
  return { name: "home" };
}

export function routeHash(route: Route): string {
  if (route.name === "editor") {
    return route.recipeId ? `#/editor/${encodeURIComponent(route.recipeId)}` : "#/editor";
  }
  return "#/";
}

export function navigate(route: Route): void {
  const next = routeHash(route);
  if (window.location.hash !== next) {
    window.location.hash = next;
  }
}

export function useHashRoute(): Route {
  const [route, setRoute] = useState<Route>(() => parseRoute(window.location.hash));

  const sync = useCallback(() => setRoute(parseRoute(window.location.hash)), []);

  useEffect(() => {
    window.addEventListener("hashchange", sync);
    return () => window.removeEventListener("hashchange", sync);
  }, [sync]);

  return route;
}
