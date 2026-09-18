import { useCallback, useState } from "react";
import { dashboardApi } from "../../api/dashboard";
import { usePoll } from "../../hooks/usePoll";
import { Badge, Button, Card, ErrorState } from "./ui";

function formatBytes(bytes: number | null): string {
  if (bytes === null) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatUptime(seconds: number): string {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (hours > 0) return `${hours} sa ${minutes} dk`;
  return `${minutes} dk`;
}

export function StatusPanel() {
  const status = usePoll(useCallback(() => dashboardApi.status(), []), 5000);
  const server = usePoll(useCallback(() => dashboardApi.serverStatus(), []), 5000);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [acting, setActing] = useState(false);

  async function runAction(action: "start" | "stop" | "restart") {
    setActing(true);
    setActionMessage(null);
    try {
      const result = await dashboardApi.serverAction(action);
      setActionMessage(result.detail);
    } catch (err) {
      setActionMessage(err instanceof Error ? err.message : "İşlem başarısız oldu");
    } finally {
      setActing(false);
      server.refresh();
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <Card
        title="Backend"
        actions={
          <div className="flex gap-2">
            <Button onClick={() => runAction("start")} disabled={acting}>
              Başlat
            </Button>
            <Button onClick={() => runAction("restart")} disabled={acting} variant="primary">
              Yeniden başlat
            </Button>
            <Button onClick={() => runAction("stop")} disabled={acting} variant="danger">
              Durdur
            </Button>
          </div>
        }
      >
        {server.error && <ErrorState message={server.error} />}
        {server.data && (
          <div className="flex flex-col gap-2 text-sm text-fg-soft">
            <div className="flex items-center gap-2">
              <Badge tone={server.data.backend_up ? "ok" : "bad"}>
                {server.data.backend_up ? "Çalışıyor" : "Kapalı"}
              </Badge>
              {server.data.tracked_pid && (
                <span className="text-xs text-fg-subtle">PID {server.data.tracked_pid}</span>
              )}
              {server.data.systemctl_available && (
                <span className="text-xs text-fg-subtle">systemd üzerinden yönetiliyor</span>
              )}
            </div>
            {actionMessage && <p className="text-xs text-fg-muted">{actionMessage}</p>}
          </div>
        )}
      </Card>

      {status.error && <ErrorState message={status.error} />}
      {status.data && (
        <div className="grid grid-cols-[repeat(auto-fit,minmax(140px,1fr))] gap-3">
          <Metric label="Çalışma süresi" value={formatUptime(status.data.uptime_seconds)} />
          <Metric label="Model" value={status.data.flash_model} />
          <Metric label="Pro model" value={status.data.pro_configured ? "yapılandırıldı" : "yok"} />
          <Metric label="Zamanlayıcı" value={status.data.scheduler_running ? "çalışıyor" : "durdu"} />
          <Metric label="Sohbet sayısı" value={String(status.data.active_conversations)} />
          <Metric label="Çalışan ajan" value={String(status.data.running_subagents)} />
          <Metric label="Çalışan görev" value={String(status.data.running_trigger_occurrences)} />
          <Metric label="Veritabanı" value={formatBytes(status.data.db_size_bytes)} />
          <Metric label="Sohbet geçmişi" value={formatBytes(status.data.checkpoint_db_size_bytes)} />
          <Metric label="Log dosyası" value={formatBytes(status.data.log_size_bytes)} />
        </div>
      )}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-line bg-panel p-3">
      <p className="text-xs text-fg-subtle">{label}</p>
      <p className="mt-1 truncate text-sm font-medium text-fg-soft">{value}</p>
    </div>
  );
}
