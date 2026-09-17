import { useCallback, useMemo, useState } from "react";
import { dashboardApi, type ToolSpecResponse } from "../../api/dashboard";
import { usePoll } from "../../hooks/usePoll";
import { Badge, Card, ErrorState } from "./ui";

function groupLabel(module: string): string {
  const leaf = module.split(".").pop() ?? module;
  return leaf.replace(/_tool$/, "").replace(/_/g, " ");
}

export function ToolsPanel() {
  const tools = usePoll(useCallback(() => dashboardApi.tools(), []), null);
  const [expanded, setExpanded] = useState<string | null>(null);

  const groups = useMemo(() => {
    if (!tools.data) return [];
    const map = new Map<string, ToolSpecResponse[]>();
    for (const tool of tools.data.tools) {
      const key = groupLabel(tool.module);
      map.set(key, [...(map.get(key) ?? []), tool]);
    }
    return Array.from(map.entries()).sort((a, b) => a[0].localeCompare(b[0]));
  }, [tools.data]);

  if (tools.error) return <ErrorState message={tools.error} />;
  if (!tools.data) return null;

  return (
    <div className="flex flex-col gap-4">
      <p className="text-xs text-slate-500">{tools.data.tools.length} araç kayıtlı</p>
      {groups.map(([group, items]) => (
        <Card key={group} title={group}>
          <div className="flex flex-col gap-1.5">
            {items.map((tool) => {
              const isExpanded = expanded === tool.name;
              return (
                <div key={tool.name} className="rounded-lg border border-surface-border bg-surface">
                  <button
                    type="button"
                    onClick={() => setExpanded(isExpanded ? null : tool.name)}
                    className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left"
                  >
                    <div>
                      <p className="text-sm font-medium text-slate-200">{tool.name}</p>
                      <p className="text-xs text-slate-500">{tool.description}</p>
                    </div>
                    <div className="flex shrink-0 items-center gap-1.5">
                      {tool.background && <Badge tone="neutral">arka plan</Badge>}
                      {tool.requires_confirmation !== false && <Badge tone="warn">onay gerekir</Badge>}
                    </div>
                  </button>
                  {isExpanded && (
                    <pre className="overflow-x-auto border-t border-surface-border px-3 py-2 text-xs text-slate-400">
                      {JSON.stringify(tool.parameters, null, 2)}
                    </pre>
                  )}
                </div>
              );
            })}
          </div>
        </Card>
      ))}
    </div>
  );
}
