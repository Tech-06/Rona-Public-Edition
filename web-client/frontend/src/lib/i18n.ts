import { en } from "../locales/en";
import { tr } from "../locales/tr";

export type Locale = "tr" | "en";

export const DEFAULT_LOCALE: Locale = "tr";
export const SUPPORTED_LOCALES: Locale[] = ["tr", "en"];

const STORAGE_KEY = "rona:lang";

export type TranslationKey = keyof typeof tr;

const CATALOGS: Record<Locale, Record<TranslationKey, string>> = { tr, en };

/** Read once at module load (see the bottom of this file) so every
 * t() call -- including ones from non-component modules like
 * lib/storage.ts, evaluated before any component mounts -- already sees
 * the right language on the very first render. LanguageProvider's own
 * lazy useState initializer reads the same readLocale(), so its first
 * render matches this without a flash. */
let active: Locale = DEFAULT_LOCALE;

export function readLocale(): Locale {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === "tr" || stored === "en") return stored;
  } catch {
    // storage unavailable (private mode, quota) - fall through
  }
  const injected = (window as unknown as { __RONA_LANG__?: string }).__RONA_LANG__;
  if (injected === "tr" || injected === "en") return injected;
  return DEFAULT_LOCALE;
}

export function writeLocale(locale: Locale): void {
  try {
    localStorage.setItem(STORAGE_KEY, locale);
  } catch {
    // storage unavailable - choice just won't persist across reloads
  }
}

export function setActiveLocale(locale: Locale): void {
  active = locale;
}

export function getActiveLocale(): Locale {
  return active;
}

/** Look up `key` in the active locale's catalog; fall back to the other
 * locale, then to the bare key itself, if it's somehow missing (the
 * `en`/`tr` key-set parity is otherwise enforced at build time -- see
 * locales/en.ts). `vars`, when given, replaces `{name}` placeholders. */
export function t(key: TranslationKey, vars?: Record<string, string | number>): string {
  const catalog = CATALOGS[active] ?? CATALOGS[DEFAULT_LOCALE];
  let template = catalog[key];
  if (template === undefined) {
    const other = active === "tr" ? "en" : "tr";
    template = CATALOGS[other][key] ?? key;
  }
  if (!vars) return template;
  return template.replace(/\{(\w+)\}/g, (match, name: string) =>
    name in vars ? String(vars[name]) : match,
  );
}

active = readLocale();
