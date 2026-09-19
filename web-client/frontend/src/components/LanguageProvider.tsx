import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import {
  getActiveLocale,
  readLocale,
  setActiveLocale,
  t as translate,
  writeLocale,
  type Locale,
  type TranslationKey,
} from "../lib/i18n";

interface LanguageContextValue {
  locale: Locale;
  setLocale: (locale: Locale) => void;
}

const LanguageContext = createContext<LanguageContextValue | null>(null);

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(() => readLocale());

  const setLocale = useCallback((next: Locale) => {
    setLocaleState(next);
    writeLocale(next);
    // Applied synchronously (not just via the effect below) so any t()
    // call made later in this same tick -- before React gets around to
    // running effects -- already sees the new language.
    setActiveLocale(next);
  }, []);

  useEffect(() => {
    setActiveLocale(locale);
    document.documentElement.lang = locale;
  }, [locale]);

  const value = useMemo(() => ({ locale, setLocale }), [locale, setLocale]);

  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>;
}

export function useLanguage(): LanguageContextValue {
  const context = useContext(LanguageContext);
  if (!context) {
    throw new Error("useLanguage must be used within a LanguageProvider");
  }
  return context;
}

/** t(), bound to the active locale via context: components call this
 * (not the plain t() from lib/i18n) so they re-render on a language
 * switch. Plain modules that aren't components/hooks (lib/storage.ts,
 * lib/toolLabels.ts) call t() from lib/i18n directly instead -- they
 * have no render cycle of their own to subscribe with, and are only
 * ever invoked from inside a component that already re-renders on
 * locale change (see useT's own call sites for the pattern). */
export function useT() {
  const { locale } = useLanguage();
  return useCallback(
    (key: TranslationKey, vars?: Record<string, string | number>) => translate(key, vars),
    [locale],
  );
}

// Re-exported so call sites that only need a one-off, non-reactive read
// (e.g. building a value outside of render) don't need a second import
// from lib/i18n.
export { getActiveLocale };
