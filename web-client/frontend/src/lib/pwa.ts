// Service worker registration + install-prompt capture for the PWA.
// Imported once from main.tsx so both start as soon as the app boots;
// useInstallPrompt.ts (and Settings > Appearance's install card) reads
// state from here rather than listening for the events itself, since
// `beforeinstallprompt` fires at most once and would be missed by any
// component that mounts after it does.

// Not yet in TS's DOM lib.
interface BeforeInstallPromptEvent extends Event {
  prompt(): Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed"; platform: string }>;
}

export function isStandaloneDisplay(): boolean {
  return (
    window.matchMedia("(display-mode: standalone)").matches ||
    // iOS Safari's own, non-standard flag -- display-mode never reports
    // standalone there even when launched from the home screen.
    (navigator as unknown as { standalone?: boolean }).standalone === true
  );
}

let deferredPrompt: BeforeInstallPromptEvent | null = null;
let installed = isStandaloneDisplay();
const listeners = new Set<() => void>();

function notify(): void {
  for (const listener of listeners) listener();
}

window.addEventListener("beforeinstallprompt", (event) => {
  // Deliberately NOT calling event.preventDefault(): Chrome's own install
  // banner and "Install app" menu entry keep working exactly as they
  // would without this file. This only keeps a reference so Settings >
  // Appearance can also offer an explicit button (see AppearanceSection.tsx).
  deferredPrompt = event as BeforeInstallPromptEvent;
  notify();
});

window.addEventListener("appinstalled", () => {
  deferredPrompt = null;
  installed = true;
  notify();
});

export function canInstall(): boolean {
  return deferredPrompt !== null;
}

export function isInstalled(): boolean {
  return installed;
}

export function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Shows the native install prompt. Resolves false if there was nothing
 * to prompt (canInstall() was already false) or the user dismissed it. */
export async function promptInstall(): Promise<boolean> {
  const prompt = deferredPrompt;
  if (!prompt) return false;
  // A captured prompt can only ever be shown once -- clear it (and notify,
  // so the install button disappears) before awaiting the user's choice.
  deferredPrompt = null;
  notify();
  await prompt.prompt();
  const choice = await prompt.userChoice;
  return choice.outcome === "accepted";
}

/** Registers sw.js (see public/sw.js) -- offline-fallback only, see that
 * file's own comment for why it never caches the app itself. Skipped in
 * dev: the Vite dev server has no /sw.js, and its own HMR already covers
 * what a service worker would otherwise be for here. */
export function registerServiceWorker(): void {
  if (!import.meta.env.PROD) return;
  if (!("serviceWorker" in navigator)) return;
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {
      // Best effort -- the app works fully without it, just without an
      // offline page when the network is down.
    });
  });
}
