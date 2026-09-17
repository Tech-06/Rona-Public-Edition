import type { View } from "../../App";
import { ConfigPanel } from "./ConfigPanel";
import { ConnectionsPanel } from "./ConnectionsPanel";
import { DataPanel } from "./DataPanel";
import { LogsPanel } from "./LogsPanel";
import { StatusPanel } from "./StatusPanel";
import { SubagentsPanel } from "./SubagentsPanel";
import { TasksPanel } from "./TasksPanel";
import { ToolsPanel } from "./ToolsPanel";

const TITLES: Record<string, string> = {
  "dashboard:status": "Durum",
  "dashboard:connections": "Bağlantılar",
  "dashboard:config": "Ayarlar",
  "dashboard:tools": "Araçlar",
  "dashboard:tasks": "Görevler",
  "dashboard:subagents": "Ajanlar",
  "dashboard:logs": "Loglar",
  "dashboard:data": "Veri",
};

export function DashboardView({ view }: { view: View }) {
  const isLogs = view === "dashboard:logs";
  return (
    <div className={`flex h-full flex-col ${isLogs ? "" : "overflow-y-auto"}`}>
      <div className="border-b border-surface-border px-6 py-4">
        <h1 className="text-lg font-semibold text-slate-100">{TITLES[view]}</h1>
      </div>
      <div className={`flex-1 px-6 py-5 ${isLogs ? "min-h-0" : ""}`}>
        {view === "dashboard:status" && <StatusPanel />}
        {view === "dashboard:connections" && <ConnectionsPanel />}
        {view === "dashboard:config" && <ConfigPanel />}
        {view === "dashboard:tools" && <ToolsPanel />}
        {view === "dashboard:tasks" && <TasksPanel />}
        {view === "dashboard:subagents" && <SubagentsPanel />}
        {view === "dashboard:logs" && <LogsPanel />}
        {view === "dashboard:data" && <DataPanel />}
      </div>
    </div>
  );
}
