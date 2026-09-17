import { useCallback, useState } from "react";
import { dashboardApi, type ProbeResponse } from "../../api/dashboard";
import { usePoll } from "../../hooks/usePoll";
import { Badge, Button, Card, ErrorState } from "./ui";

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
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          <ConnectionRow
            label="Flash model"
            ok={data.flash_configured}
            probe={probe?.llm}
          />
          <ConnectionRow label="Pro model" ok={data.pro_configured} />
          <ConnectionRow label="Tavily (web arama)" ok={data.tavily_configured} probe={probe?.web_search} />
          <ConnectionRow label="DeepL (çeviri)" ok={data.deepl_configured} probe={probe?.translate} />
          <ConnectionRow label="OpenWeather" ok={data.openweather_configured} probe={probe?.weather} />
          <ConnectionRow label="Gemini embedding (hafıza)" ok={data.gemini_embedding_configured} />
          <ConnectionRow label="rona.db" ok={data.db_present} />
          <ConnectionRow label="Sohbet geçmişi (checkpoint)" ok={data.checkpoint_db_present} />
        </div>
      </Card>

      <Card title="Google hesapları">
        <div className="flex flex-col gap-2">
          {data.google_accounts.map((account) => (
            <div
              key={account.account}
              className="flex flex-wrap items-center gap-2 rounded-lg border border-surface-border bg-surface px-3 py-2 text-sm"
            >
              <span className="font-medium text-slate-200">{account.account}</span>
              <Badge tone={account.token_present ? "ok" : "bad"}>
                {account.token_present ? "token var" : "token yok"}
              </Badge>
              {account.calendar && <Badge tone="neutral">takvim</Badge>}
              {account.contacts && <Badge tone="neutral">kişiler</Badge>}
              {account.mail && <Badge tone="neutral">mail</Badge>}
              {probe?.google[account.account] && (
                <Badge tone={probe.google[account.account].ok ? "ok" : "bad"}>
                  {probe.google[account.account].ok ? "doğrulandı" : probe.google[account.account].detail}
                </Badge>
              )}
            </div>
          ))}
          {!data.google_credentials_file_present && (
            <p className="text-xs text-amber-300">credentials.json bulunamadı.</p>
          )}
        </div>
      </Card>
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
    <div className="flex items-center justify-between gap-2 rounded-lg border border-surface-border bg-surface px-3 py-2 text-sm">
      <span className="text-slate-300">{label}</span>
      <div className="flex items-center gap-2">
        <Badge tone={ok ? "ok" : "bad"}>{ok ? "yapılandırıldı" : "eksik"}</Badge>
        {probe && (
          <Badge tone={probe.ok ? "ok" : "bad"}>{probe.ok ? "canlı" : "hata"}</Badge>
        )}
      </div>
    </div>
  );
}
