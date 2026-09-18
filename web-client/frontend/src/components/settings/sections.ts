import type { ComponentType, SVGProps } from "react";
import type { SettingsSectionId } from "../../types";
import { ConfigPanel } from "../dashboard/ConfigPanel";
import { ConnectionsPanel } from "../dashboard/ConnectionsPanel";
import { DataPanel } from "../dashboard/DataPanel";
import { LogsPanel } from "../dashboard/LogsPanel";
import { StatusPanel } from "../dashboard/StatusPanel";
import { SubagentsPanel } from "../dashboard/SubagentsPanel";
import { TasksPanel } from "../dashboard/TasksPanel";
import { ToolsPanel } from "../dashboard/ToolsPanel";
import {
  ActivityIcon,
  BotIcon,
  CalendarClockIcon,
  ChatBubbleIcon,
  DatabaseIcon,
  PaletteIcon,
  PlugIcon,
  SlidersIcon,
  TerminalIcon,
  WrenchIcon,
} from "../ui/icons";
import { AppearanceSection } from "./AppearanceSection";
import { ChatsSection } from "./ChatsSection";

export interface SettingsSection {
  id: SettingsSectionId;
  label: string;
  icon: ComponentType<SVGProps<SVGSVGElement>>;
  component: ComponentType;
  /** The section manages its own internal scrolling (Logs has a
   * fixed-height tail view) -- the modal must not ALSO make this section's
   * wrapper scrollable, or the inner region grows unbounded and pushes
   * the modal off-screen. */
  selfScrolling?: boolean;
}

// Single source of truth for the settings rail. This replaces the old
// duplicated pair of lists (Sidebar.tsx's DASHBOARD_ITEMS and
// DashboardView.tsx's TITLES) that had to be kept in sync by hand.
//
// "advanced" (the raw .env field editor, formerly labelled "Ayarlar") is
// deliberately relabelled "Gelişmiş" here: the whole modal is now "Ayarlar",
// so a second, identically-named entry inside it would be confusing.
export const SETTINGS_SECTIONS: SettingsSection[] = [
  { id: "appearance", label: "Görünüm", icon: PaletteIcon, component: AppearanceSection },
  { id: "chats", label: "Sohbetler", icon: ChatBubbleIcon, component: ChatsSection },
  { id: "status", label: "Durum", icon: ActivityIcon, component: StatusPanel },
  { id: "connections", label: "Bağlantılar", icon: PlugIcon, component: ConnectionsPanel },
  { id: "advanced", label: "Gelişmiş", icon: SlidersIcon, component: ConfigPanel },
  { id: "tools", label: "Araçlar", icon: WrenchIcon, component: ToolsPanel },
  { id: "tasks", label: "Görevler", icon: CalendarClockIcon, component: TasksPanel },
  { id: "subagents", label: "Ajanlar", icon: BotIcon, component: SubagentsPanel },
  { id: "logs", label: "Loglar", icon: TerminalIcon, component: LogsPanel, selfScrolling: true },
  { id: "data", label: "Veri", icon: DatabaseIcon, component: DataPanel },
];

export const DEFAULT_SETTINGS_SECTION: SettingsSectionId = "chats";

export function findSection(id: SettingsSectionId): SettingsSection {
  return SETTINGS_SECTIONS.find((section) => section.id === id) ?? SETTINGS_SECTIONS[0];
}
