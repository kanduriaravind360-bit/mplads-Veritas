import { useCallback, useEffect, useState } from "react";

const THEME_KEY = "sentinel.theme";
export type Theme = "dark" | "light";

function current(): Theme {
  return document.documentElement.classList.contains("dark") ? "dark" : "light";
}

export function useTheme(): { theme: Theme; toggle: () => void } {
  const [theme, setTheme] = useState<Theme>(current);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
    try {
      localStorage.setItem(THEME_KEY, theme);
    } catch {
      /* ignore */
    }
    window.dispatchEvent(new CustomEvent("sentinel:theme", { detail: theme }));
  }, [theme]);

  useEffect(() => {
    const sync = (event: Event) => setTheme((event as CustomEvent<Theme>).detail);
    window.addEventListener("sentinel:theme", sync);
    return () => window.removeEventListener("sentinel:theme", sync);
  }, []);

  const toggle = useCallback(() => setTheme((t) => (t === "dark" ? "light" : "dark")), []);
  return { theme, toggle };
}

/** Resolve a theme token ("line") to a concrete colour, for canvas renderers that cannot read CSS variables. */
export function resolveToken(name: string, alpha = 1): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(`--${name}`).trim();
  return value ? `rgb(${value} / ${alpha})` : "rgb(128 128 128 / 0.5)";
}
