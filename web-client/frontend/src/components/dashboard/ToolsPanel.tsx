import { useCallback, useMemo, useState } from "react";
import { dashboardApi, type ToolSpecResponse } from "../../api/dashboard";
import { usePoll } from "../../hooks/usePoll";
import { useT } from "../LanguageProvider";
import { Badge, Card, ErrorState } from "./ui";

function groupLabel(module: string): string {
  const leaf = module.split(".").pop() ?? module;
  return leaf.replace(/_tool$/, "").replace(/_/g, " ");
}

export function ToolsPanel() {
  const t = useT();
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
      <p className="text-xs text-fg-subtle">{t("tools.registered_count", { count: tools.data.tools.length })}</p>
      {groups.map(([group, items]) => (
        <Card key={group} title={group}>
          <div className="flex flex-col gap-1.5">
            {items.map((tool) => {
              const isExpanded = expanded === tool.name;
              return (
                <div key={tool.name} className="rounded-lg border border-line bg-app">
                  <button
                    type="button"
                    onClick={() => setExpanded(isExpanded ? null : tool.name)}
                    className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left"
                  >
                    <div>
                      <p className="text-sm font-medium text-fg-soft">{tool.name}</p>
                      <p className="text-xs text-fg-subtle">{tool.description}</p>
                    </div>
                    <div className="flex shrink-0 items-center gap-1.5">
                      {tool.background && <Badge tone="neutral">{t("tools.background_badge")}</Badge>}
                      {tool.requires_confirmation !== false && (
                        <Badge tone="warn">{t("tools.requires_confirmation_badge")}</Badge>
                      )}
                    </div>
                  </button>
                  {isExpanded && (
                    <pre className="overflow-x-auto border-t border-line px-3 py-2 text-xs text-fg-muted">
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
