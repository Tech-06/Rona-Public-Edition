export type ThemeMode = "system" | "light" | "dark";

const STORAGE_KEY = "rona:theme";

export function readThemeMode(): ThemeMode {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === "light" || stored === "dark" || stored === "system") {
      return stored;
    }
  } catch {
    // storage unavailable (private mode, quota) - fall back to system
  }
  return "system";
}

export function writeThemeMode(mode: ThemeMode): void {
  try {
    localStorage.setItem(STORAGE_KEY, mode);
  } catch {
    // storage unavailable - theme choice just won't persist across reloads
  }
}

export function resolveDark(mode: ThemeMode): boolean {
  if (mode === "dark") return true;
  if (mode === "light") return false;
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

/** Mirrors the inline bootstrap script in index.html, so React takes over
 * without changing anything the first paint already decided -- including
 * the <meta name="theme-color"> that the installed PWA's status bar/task
 * switcher chrome picks up, which also needs to follow a later switch
 * made from Settings > Appearance, not just the initial page load. */
export function applyTheme(dark: boolean): void {
  const root = document.documentElement;
  root.classList.toggle("dark", dark);
  root.style.colorScheme = dark ? "dark" : "light";
  const themeColorMeta = document.querySelector('meta[name="theme-color"]');
  if (themeColorMeta) themeColorMeta.setAttribute("content", dark ? "#171717" : "#f7f7f8");
}
