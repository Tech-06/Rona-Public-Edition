import { Button } from "../dashboard/ui";

interface Props {
  visible: boolean;
  onRestart: () => void | Promise<void>;
  canAutoRestart: boolean;
  restarting?: boolean;
}

/** Shared by ChatsSection and ConfigPanel: both write settings that only
 * take effect after a backend restart (get_settings() is @lru_cache'd and
 * uvicorn's --reload watches *.py, not .env). `/host/server/restart` only
 * works when webui is tracking the backend process or systemctl is
 * available -- otherwise it silently can't do anything, so canAutoRestart
 * gates whether we offer the button at all instead of showing a button
 * that fails. */
export function RestartBanner({ visible, onRestart, canAutoRestart, restarting }: Props) {
  if (!visible) return null;
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-warn/40 bg-warn/10 px-4 py-3 text-sm text-warn-text">
      <span>Değişikliklerin uygulanması için sunucunun yeniden başlatılması gerekiyor.</span>
      {canAutoRestart ? (
        <Button onClick={onRestart} variant="primary" disabled={restarting}>
          {restarting ? "Yeniden başlatılıyor..." : "Şimdi yeniden başlat"}
        </Button>
      ) : (
        <span className="text-xs text-warn-text/80">
          Otomatik yeniden başlatma kullanılamıyor — backend'i elle yeniden başlat (python run.py).
        </span>
      )}
    </div>
  );
}
