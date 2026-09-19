import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useFocusTrap } from "../../hooks/useFocusTrap";
import { useMediaQuery } from "../../hooks/useMediaQuery";
import type { SettingsSectionId } from "../../types";
import { useT } from "../LanguageProvider";
import { ChevronLeftIcon, XIcon } from "../ui/icons";
import { DEFAULT_SETTINGS_SECTION, findSection, SETTINGS_SECTIONS } from "./sections";
import { SettingsRail } from "./SettingsRail";

const LAST_SECTION_KEY = "rona:settings:lastSection";

function readLastSection(): SettingsSectionId {
  try {
    const stored = localStorage.getItem(LAST_SECTION_KEY);
    if (stored && SETTINGS_SECTIONS.some((section) => section.id === stored)) {
      return stored as SettingsSectionId;
    }
  } catch {
    // ignore
  }
  return DEFAULT_SETTINGS_SECTION;
}

interface Props {
  open: boolean;
  onClose: () => void;
  initialSection?: SettingsSectionId;
}

export function SettingsModal({ open, onClose, initialSection }: Props) {
  const t = useT();
  const isDesktop = useMediaQuery("(min-width: 768px)");
  const [activeSection, setActiveSection] = useState<SettingsSectionId>(
    () => initialSection ?? readLastSection(),
  );
  // On mobile this is the navigation stack depth: null = section list,
  // an id = that section's detail view. Desktop ignores it and always
  // shows both the rail and activeSection side by side.
  const [mobileSection, setMobileSection] = useState<SettingsSectionId | null>(null);
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const initial = initialSection ?? readLastSection();
    setActiveSection(initial);
    setMobileSection(initialSection ?? null);
  }, [open, initialSection]);

  useFocusTrap(dialogRef, open, onClose);

  useEffect(() => {
    if (!open) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, [open]);

  function selectSection(id: SettingsSectionId) {
    setActiveSection(id);
    setMobileSection(id);
    try {
      localStorage.setItem(LAST_SECTION_KEY, id);
    } catch {
      // ignore
    }
  }

  if (!open) return null;

  const showingMobileDetail = !isDesktop && mobileSection !== null;
  const section = findSection(isDesktop ? activeSection : mobileSection ?? activeSection);

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-0 sm:p-4">
      <button
        type="button"
        aria-label={t("settings.close")}
        onClick={onClose}
        className="absolute inset-0 cursor-default"
      />
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label={t("settings.modal_title")}
        tabIndex={-1}
        className="relative flex h-full w-full flex-col overflow-hidden bg-panel text-fg shadow-2xl outline-none sm:h-[85vh] sm:max-h-[720px] sm:w-full sm:max-w-5xl sm:rounded-2xl sm:border sm:border-line"
      >
        <div className="hidden items-center justify-between border-b border-line px-5 py-3 md:flex">
          <h2 className="text-sm font-semibold text-fg">{t("settings.modal_title")}</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label={t("settings.close")}
            className="rounded-lg p-1.5 text-fg-muted transition-colors hover:bg-elevated hover:text-fg-soft"
          >
            <XIcon className="h-4 w-4" />
          </button>
        </div>

        <div className="flex items-center justify-between border-b border-line px-4 py-3 md:hidden">
          {showingMobileDetail ? (
            <button
              type="button"
              onClick={() => setMobileSection(null)}
              className="flex items-center gap-1 text-sm text-fg-muted"
            >
              <ChevronLeftIcon className="h-4 w-4" />
              {t("settings.modal_title")}
            </button>
          ) : (
            <h2 className="text-sm font-semibold text-fg">{t("settings.modal_title")}</h2>
          )}
          <button
            type="button"
            onClick={onClose}
            aria-label={t("settings.close")}
            className="rounded-lg p-1.5 text-fg-muted transition-colors hover:bg-elevated hover:text-fg-soft"
          >
            <XIcon className="h-4 w-4" />
          </button>
        </div>

        <div className="flex min-h-0 flex-1">
          <div className="hidden w-56 shrink-0 overflow-y-auto border-r border-line p-3 md:block">
            <SettingsRail active={activeSection} onSelect={selectSection} />
          </div>

          {!isDesktop && !showingMobileDetail && (
            <div className="flex-1 overflow-y-auto p-3">
              <SettingsRail active={activeSection} onSelect={selectSection} />
            </div>
          )}

          {(isDesktop || showingMobileDetail) && (
            <div
              className={`flex min-h-0 flex-1 flex-col ${section.selfScrolling ? "" : "overflow-y-auto"}`}
            >
              {!isDesktop && (
                <h3 className="px-4 pt-3 text-xs font-medium uppercase tracking-wide text-fg-subtle">
                  {t(section.labelKey)}
                </h3>
              )}
              <div
                className={
                  section.selfScrolling ? "flex min-h-0 flex-1 flex-col p-4" : "p-4"
                }
              >
                <section.component />
              </div>
            </div>
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}
