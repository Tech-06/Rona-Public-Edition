import type { SettingsSectionId } from "../../types";
import { useT } from "../LanguageProvider";
import { SETTINGS_SECTIONS } from "./sections";

interface Props {
  active: SettingsSectionId;
  onSelect: (id: SettingsSectionId) => void;
  className?: string;
}

export function SettingsRail({ active, onSelect, className = "" }: Props) {
  const t = useT();
  return (
    <nav className={`flex flex-col gap-0.5 ${className}`}>
      {SETTINGS_SECTIONS.map((section) => {
        const Icon = section.icon;
        const isActive = section.id === active;
        return (
          <button
            key={section.id}
            type="button"
            onClick={() => onSelect(section.id)}
            aria-current={isActive ? "true" : undefined}
            className={`flex items-center gap-2.5 rounded-lg px-3 py-2 text-left text-sm transition-colors ${
              isActive ? "bg-elevated text-fg" : "text-fg-muted hover:bg-elevated hover:text-fg-soft"
            }`}
          >
            <Icon className="h-4 w-4 shrink-0" />
            <span className="truncate">{t(section.labelKey)}</span>
          </button>
        );
      })}
    </nav>
  );
}
