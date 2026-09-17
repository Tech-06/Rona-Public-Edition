import { useCallback, useEffect, useState } from "react";
import { dashboardApi } from "./api/dashboard";
import { ChatView } from "./components/chat/ChatView";
import { DashboardView } from "./components/dashboard/DashboardView";
import { Sidebar } from "./components/layout/Sidebar";
import { deleteConversation, loadIndex } from "./lib/storage";
import type { ConversationSummary } from "./types";

export type View =
  | "chat"
  | "dashboard:status"
  | "dashboard:connections"
  | "dashboard:config"
  | "dashboard:tools"
  | "dashboard:tasks"
  | "dashboard:subagents"
  | "dashboard:logs"
  | "dashboard:data";

export default function App() {
  const [view, setView] = useState<View>("chat");
  const [chatKey, setChatKey] = useState(0);
  const [initialConversationId, setInitialConversationId] = useState<string | null>(null);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [conversations, setConversations] = useState<ConversationSummary[]>(() => loadIndex());
  const [backendUp, setBackendUp] = useState<boolean | null>(null);

  const refreshConversations = useCallback(() => {
    setConversations(loadIndex());
  }, []);

  const handleConversationId = useCallback(
    (id: string) => {
      setActiveConversationId(id);
      refreshConversations();
    },
    [refreshConversations],
  );

  function newChat() {
    setInitialConversationId(null);
    setActiveConversationId(null);
    setChatKey((key) => key + 1);
    setView("chat");
  }

  function selectConversation(id: string) {
    setInitialConversationId(id);
    setActiveConversationId(id);
    setChatKey((key) => key + 1);
    setView("chat");
  }

  function removeConversation(id: string) {
    deleteConversation(id);
    refreshConversations();
    if (activeConversationId === id) {
      newChat();
    }
  }

  useEffect(() => {
    let cancelled = false;
    async function poll() {
      try {
        await dashboardApi.status();
        if (!cancelled) setBackendUp(true);
      } catch {
        if (!cancelled) setBackendUp(false);
      }
    }
    poll();
    const id = setInterval(poll, 10000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  return (
    <div className="flex h-screen bg-surface">
      <Sidebar
        activeView={view}
        onViewChange={setView}
        conversations={conversations}
        activeConversationId={view === "chat" ? activeConversationId : null}
        onSelectConversation={selectConversation}
        onDeleteConversation={removeConversation}
        onNewChat={newChat}
        backendUp={backendUp}
      />
      <main className="min-w-0 flex-1">
        {view === "chat" ? (
          <ChatView
            key={chatKey}
            conversationId={initialConversationId}
            onConversationId={handleConversationId}
          />
        ) : (
          <DashboardView view={view} />
        )}
      </main>
    </div>
  );
}
