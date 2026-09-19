import { useLanguage, useT } from "../LanguageProvider";
import type { ThemeMode } from "../../lib/theme";
import type { Locale } from "../../lib/i18n";
import { useTheme } from "../ThemeProvider";
import { CheckIcon, MonitorIcon, MoonIcon, SunIcon } from "../ui/icons";

export function AppearanceSection() {
  const t = useT();
  const { mode, setMode } = useTheme();
  const { locale, setLocale } = useLanguage();

  const themeOptions: Array<{ mode: ThemeMode; label: string; icon: typeof SunIcon }> = [
    { mode: "system", label: t("appearance.theme_system"), icon: MonitorIcon },
    { mode: "light", label: t("appearance.theme_light"), icon: SunIcon },
    { mode: "dark", label: t("appearance.theme_dark"), icon: MoonIcon },
  ];

  const languageOptions: Array<{ locale: Locale; label: string }> = [
    { locale: "tr", label: t("appearance.language_tr") },
    { locale: "en", label: t("appearance.language_en") },
  ];

  return (
    <div className="flex flex-col gap-4">
      <div className="rounded-xl border border-line bg-panel p-4">
        <p className="text-sm font-semibold text-fg-soft">{t("appearance.theme_title")}</p>
        <p className="mt-1 text-xs text-fg-subtle">{t("appearance.theme_description")}</p>
        <div className="mt-3 grid grid-cols-3 gap-2">
          {themeOptions.map(({ mode: optionMode, label, icon: Icon }) => {
            const active = mode === optionMode;
            return (
              <button
                key={optionMode}
                type="button"
                onClick={() => setMode(optionMode)}
                className={`flex flex-col items-center gap-2 rounded-lg border px-3 py-3 text-sm transition-colors ${
                  active
                    ? "border-accent bg-accent/10 text-accent-text"
                    : "border-line text-fg-muted hover:bg-elevated hover:text-fg-soft"
                }`}
              >
                <Icon className="h-5 w-5" />
                <span className="flex items-center gap-1">
                  {label}
                  {active && <CheckIcon className="h-3.5 w-3.5" />}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      <div className="rounded-xl border border-line bg-panel p-4">
        <p className="text-sm font-semibold text-fg-soft">{t("appearance.language_title")}</p>
        <p className="mt-1 text-xs text-fg-subtle">{t("appearance.language_description")}</p>
        <div className="mt-3 grid grid-cols-2 gap-2">
          {languageOptions.map(({ locale: optionLocale, label }) => {
            const active = locale === optionLocale;
            return (
              <button
                key={optionLocale}
                type="button"
                onClick={() => setLocale(optionLocale)}
                className={`flex items-center justify-center gap-2 rounded-lg border px-3 py-3 text-sm transition-colors ${
                  active
                    ? "border-accent bg-accent/10 text-accent-text"
                    : "border-line text-fg-muted hover:bg-elevated hover:text-fg-soft"
                }`}
              >
                <span>{label}</span>
                {active && <CheckIcon className="h-3.5 w-3.5" />}
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
