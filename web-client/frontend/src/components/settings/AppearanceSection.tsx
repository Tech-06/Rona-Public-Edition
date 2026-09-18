import type { ThemeMode } from "../../lib/theme";
import { useTheme } from "../ThemeProvider";
import { CheckIcon, MonitorIcon, MoonIcon, SunIcon } from "../ui/icons";

const OPTIONS: Array<{ mode: ThemeMode; label: string; icon: typeof SunIcon }> = [
  { mode: "system", label: "Sistem", icon: MonitorIcon },
  { mode: "light", label: "Açık", icon: SunIcon },
  { mode: "dark", label: "Koyu", icon: MoonIcon },
];

export function AppearanceSection() {
  const { mode, setMode } = useTheme();

  return (
    <div className="flex flex-col gap-4">
      <div className="rounded-xl border border-line bg-panel p-4">
        <p className="text-sm font-semibold text-fg-soft">Tema</p>
        <p className="mt-1 text-xs text-fg-subtle">
          Arayüzün açık, koyu ya da işletim sistemi ayarını takip eden bir görünümde çalışmasını
          seç.
        </p>
        <div className="mt-3 grid grid-cols-3 gap-2">
          {OPTIONS.map(({ mode: optionMode, label, icon: Icon }) => {
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
    </div>
  );
}
