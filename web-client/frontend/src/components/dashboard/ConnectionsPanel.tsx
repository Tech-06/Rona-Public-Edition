import { useCallback, useState } from "react";
import { dashboardApi, type PackageStatus, type ProbeResponse } from "../../api/dashboard";
import { usePoll } from "../../hooks/usePoll";
import { Badge, Button, Card, EmptyState, ErrorState } from "./ui";

export function ConnectionsPanel() {
  const connections = usePoll(useCallback(() => dashboardApi.connections(), []), 15000);
  const [probe, setProbe] = useState<ProbeResponse | null>(null);
  const [probing, setProbing] = useState(false);
  const [probeError, setProbeError] = useState<string | null>(null);

  async function runProbe() {
    setProbing(true);
    setProbeError(null);
    try {
      setProbe(await dashboardApi.probeConnections());
    } catch (err) {
      setProbeError(err instanceof Error ? err.message : "Test başarısız oldu");
    } finally {
      setProbing(false);
    }
  }

  if (connections.error) return <ErrorState message={connections.error} />;
  if (!connections.data) return null;
  const data = connections.data;

  return (
    <div className="flex flex-col gap-4">
      <Card
        title="Bağlantılar"
        actions={
          <Button onClick={runProbe} disabled={probing} variant="primary">
            {probing ? "Test ediliyor..." : "Şimdi test et"}
          </Button>
        }
      >
        {probeError && <ErrorState message={probeError} />}
        <div className="grid grid-cols-[repeat(auto-fit,minmax(240px,1fr))] gap-2">
          <ConnectionRow
            label="Flash model"
            ok={data.flash_configured}
            probe={probe?.llm}
          />
          <ConnectionRow label="Pro model" ok={data.pro_configured} />
          <ConnectionRow label="Gemini embedding (hafıza)" ok={data.gemini_embedding_configured} />
          <ConnectionRow label="rona.db" ok={data.db_present} />
          <ConnectionRow label="Sohbet geçmişi (checkpoint)" ok={data.checkpoint_db_present} />
        </div>
      </Card>

      <Card title="Araç paketleri">
        {data.packages.length === 0 ? (
          <EmptyState>
            Kurulu isteğe bağlı araç paketi yok. Eklemek için:{" "}
            <code className="rounded bg-app px-1 py-0.5 text-xs">
              python -m toolbox.manager install &lt;paket_id&gt;
            </code>
          </EmptyState>
        ) : (
          <div className="flex flex-col gap-2">
            {data.packages.map((pkg) => (
              <PackageRow key={pkg.id} pkg={pkg} probe={probe?.packages[pkg.id]} />
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}

function PackageRow({
  pkg,
  probe,
}: {
  pkg: PackageStatus;
  probe?: { ok: boolean; detail: string };
}) {
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-lg border border-line bg-app px-3 py-2 text-sm">
      <div className="min-w-0 flex-1">
        <p className="font-medium text-fg-soft">{pkg.name}</p>
        <p className="text-xs text-fg-subtle">{pkg.description}</p>
      </div>
      <Badge tone={pkg.configured ? "ok" : "warn"}>
        {pkg.configured ? "yapılandırıldı" : `eksik: ${pkg.missing_config.join(", ")}`}
      </Badge>
      {probe && (
        <Badge tone={probe.ok ? "ok" : "bad"}>{probe.ok ? "canlı" : probe.detail}</Badge>
      )}
    </div>
  );
}

function ConnectionRow({
  label,
  ok,
  probe,
}: {
  label: string;
  ok: boolean;
  probe?: { ok: boolean; detail: string };
}) {
  return (
    <div className="flex items-center justify-between gap-2 rounded-lg border border-line bg-app px-3 py-2 text-sm">
      <span className="text-fg-soft">{label}</span>
      <div className="flex items-center gap-2">
        <Badge tone={ok ? "ok" : "bad"}>{ok ? "yapılandırıldı" : "eksik"}</Badge>
        {probe && (
          <Badge tone={probe.ok ? "ok" : "bad"}>{probe.ok ? "canlı" : "hata"}</Badge>
        )}
      </div>
    </div>
  );
}
