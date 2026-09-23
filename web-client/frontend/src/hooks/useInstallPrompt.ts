import { useEffect, useState } from "react";
import * as pwa from "../lib/pwa";

export interface InstallPromptState {
  /** True once the browser has fired beforeinstallprompt and it hasn't
   * been consumed yet -- Chrome/Edge only; Firefox and iOS Safari never
   * fire this event, so the install card stays hidden there even though
   * the OS may still let the user install/add-to-home-screen by hand. */
  canInstall: boolean;
  /** Already running as the installed app (standalone display mode, or
   * iOS Safari's non-standard navigator.standalone) -- Settings hides the
   * install card entirely once this is true. */
  isStandalone: boolean;
  /** https, or localhost -- what the browser's own install/service-worker
   * gating requires. Surfaced so Settings can explain why the install
   * card is missing on a plain http:// LAN address. */
  isSecure: boolean;
  /** Shows the native install prompt; resolves true if the user accepted
   * it. See lib/pwa.ts's promptInstall(). */
  promptInstall: () => Promise<boolean>;
}

export function useInstallPrompt(): InstallPromptState {
  const [canInstall, setCanInstall] = useState(pwa.canInstall());
  const [isStandalone, setIsStandalone] = useState(pwa.isInstalled());

  useEffect(() => {
    function update() {
      setCanInstall(pwa.canInstall());
      setIsStandalone(pwa.isInstalled());
    }
    update();
    return pwa.subscribe(update);
  }, []);

  return {
    canInstall,
    isStandalone,
    isSecure: window.isSecureContext,
    promptInstall: pwa.promptInstall,
  };
}
