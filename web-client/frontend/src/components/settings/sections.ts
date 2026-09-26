import type { ComponentType, SVGProps } from "react";
import type { TranslationKey } from "../../lib/i18n";
import type { SettingsSectionId } from "../../types";
import { ConfigPanel } from "../dashboard/ConfigPanel";
import { ConnectionsPanel } from "../dashboard/ConnectionsPanel";
import { DataPanel } from "../dashboard/DataPanel";
import { LogsPanel } from "../dashboard/LogsPanel";
import { PromptsPanel } from "../dashboard/PromptsPanel";
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
  PencilIcon,
  PlugIcon,
  SlidersIcon,
  TerminalIcon,
  WrenchIcon,
} from "../ui/icons";
import { AppearanceSection } from "./AppearanceSection";
import { ChatsSection } from "./ChatsSection";

export interface SettingsSection {
  id: SettingsSectionId;
  labelKey: TranslationKey;
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
  { id: "appearance", labelKey: "settings.section_appearance", icon: PaletteIcon, component: AppearanceSection },
  { id: "chats", labelKey: "settings.section_chats", icon: ChatBubbleIcon, component: ChatsSection },
  { id: "status", labelKey: "settings.section_status", icon: ActivityIcon, component: StatusPanel },
  { id: "connections", labelKey: "settings.section_connections", icon: PlugIcon, component: ConnectionsPanel },
  { id: "advanced", labelKey: "settings.section_advanced", icon: SlidersIcon, component: ConfigPanel },
  { id: "prompts", labelKey: "settings.section_prompts", icon: PencilIcon, component: PromptsPanel },
  { id: "tools", labelKey: "settings.section_tools", icon: WrenchIcon, component: ToolsPanel },
  { id: "tasks", labelKey: "settings.section_tasks", icon: CalendarClockIcon, component: TasksPanel },
  { id: "subagents", labelKey: "settings.section_subagents", icon: BotIcon, component: SubagentsPanel },
  { id: "logs", labelKey: "settings.section_logs", icon: TerminalIcon, component: LogsPanel, selfScrolling: true },
  { id: "data", labelKey: "settings.section_data", icon: DatabaseIcon, component: DataPanel },
];

export const DEFAULT_SETTINGS_SECTION: SettingsSectionId = "chats";

export function findSection(id: SettingsSectionId): SettingsSection {
  return SETTINGS_SECTIONS.find((section) => section.id === id) ?? SETTINGS_SECTIONS[0];
}
