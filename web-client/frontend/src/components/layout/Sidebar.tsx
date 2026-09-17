import type { ConversationSummary } from "../../types";
import type { View } from "../../App";

interface NavItem {
  view: View;
  label: string;
}

const DASHBOARD_ITEMS: NavItem[] = [
  { view: "dashboard:status", label: "Durum" },
  { view: "dashboard:connections", label: "Bağlantılar" },
  { view: "dashboard:config", label: "Ayarlar" },
  { view: "dashboard:tools", label: "Araçlar" },
  { view: "dashboard:tasks", label: "Görevler" },
  { view: "dashboard:subagents", label: "Ajanlar" },
  { view: "dashboard:logs", label: "Loglar" },
  { view: "dashboard:data", label: "Veri" },
];

interface Props {
  activeView: View;
  onViewChange: (view: View) => void;
  conversations: ConversationSummary[];
  activeConversationId: string | null;
  onSelectConversation: (id: string) => void;
  onDeleteConversation: (id: string) => void;
  onNewChat: () => void;
  backendUp: boolean | null;
}

export function Sidebar({
  activeView,
  onViewChange,
  conversations,
  activeConversationId,
  onSelectConversation,
  onDeleteConversation,
  onNewChat,
  backendUp,
}: Props) {
  return (
    <aside className="flex h-full w-64 shrink-0 flex-col border-r border-surface-border bg-surface-raised">
      <div className="flex items-center gap-2 px-4 py-4">
        <div className="flex h-7 w-7 items-center justify-center rounded-full bg-sky-600 text-sm font-semibold text-white">
          R
        </div>
        <span className="text-sm font-semibold text-slate-100">Rona</span>
        <span
          className={`ml-auto h-2 w-2 rounded-full ${
            backendUp === null ? "bg-slate-600" : backendUp ? "bg-emerald-500" : "bg-rose-500"
          }`}
          title={backendUp === null ? "Kontrol ediliyor" : backendUp ? "Backend açık" : "Backend kapalı"}
        />
      </div>

      <div className="px-3">
        <button
          type="button"
          onClick={onNewChat}
          className={`w-full rounded-lg border px-3 py-2 text-left text-sm transition-colors ${
            activeView === "chat" && !activeConversationId
              ? "border-sky-500/50 bg-sky-500/10 text-sky-200"
              : "border-surface-border text-slate-300 hover:bg-surface"
          }`}
        >
          + Yeni sohbet
        </button>
      </div>

      <div className="mt-3 flex-1 overflow-y-auto px-3">
        <p className="px-1 pb-1 text-xs font-medium uppercase tracking-wide text-slate-500">
          Sohbetler
        </p>
        <div className="flex flex-col gap-0.5">
          {conversations.map((conversation) => (
            <div
              key={conversation.conversationId}
              className={`group flex items-center rounded-lg pr-1 transition-colors ${
                activeView === "chat" && activeConversationId === conversation.conversationId
                  ? "bg-surface"
                  : "hover:bg-surface"
              }`}
            >
              <button
                type="button"
                onClick={() => onSelectConversation(conversation.conversationId)}
                className={`min-w-0 flex-1 truncate rounded-lg px-2.5 py-1.5 text-left text-sm transition-colors ${
                  activeView === "chat" && activeConversationId === conversation.conversationId
                    ? "text-slate-100"
                    : "text-slate-400 group-hover:text-slate-200"
                }`}
              >
                {conversation.title || "Sohbet"}
              </button>
              <button
                type="button"
                onClick={(event) => {
                  event.stopPropagation();
                  if (confirm("Bu sohbeti silmek istediğine emin misin?")) {
                    onDeleteConversation(conversation.conversationId);
                  }
                }}
                title="Sohbeti sil"
                className="shrink-0 rounded-md px-1.5 py-1 text-slate-600 opacity-0 transition-opacity hover:text-rose-400 group-hover:opacity-100"
              >
                ×
              </button>
            </div>
          ))}
          {conversations.length === 0 && (
            <p className="px-2.5 py-1.5 text-xs text-slate-600">Henüz sohbet yok.</p>
          )}
        </div>
      </div>

      <div className="border-t border-surface-border px-3 py-3">
        <p className="px-1 pb-1 text-xs font-medium uppercase tracking-wide text-slate-500">
          Panel
        </p>
        <div className="flex flex-col gap-0.5">
          {DASHBOARD_ITEMS.map((item) => (
            <button
              key={item.view}
              type="button"
              onClick={() => onViewChange(item.view)}
              className={`rounded-lg px-2.5 py-1.5 text-left text-sm transition-colors ${
                activeView === item.view
                  ? "bg-surface text-slate-100"
                  : "text-slate-400 hover:bg-surface hover:text-slate-200"
              }`}
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>
    </aside>
  );
}
