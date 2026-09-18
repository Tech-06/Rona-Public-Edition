import { useCallback, useEffect, useState } from "react";
import { dashboardApi } from "./api/dashboard";
import { ChatView } from "./components/chat/ChatView";
import { MobileTopBar } from "./components/layout/MobileTopBar";
import { Sidebar } from "./components/layout/Sidebar";
import { SettingsModal } from "./components/settings/SettingsModal";
import { useConversationSync } from "./hooks/useConversationSync";
import { useMediaQuery } from "./hooks/useMediaQuery";
import { deleteConversation, loadIndex, onConversationsChanged } from "./lib/storage";
import type { ConversationSummary } from "./types";

export default function App() {
  const [chatKey, setChatKey] = useState(0);
  const [initialConversationId, setInitialConversationId] = useState<string | null>(null);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [conversations, setConversations] = useState<ConversationSummary[]>(() => loadIndex());
  const [backendUp, setBackendUp] = useState<boolean | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const isDesktop = useMediaQuery("(min-width: 768px)");

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
    setDrawerOpen(false);
  }

  function selectConversation(id: string) {
    setInitialConversationId(id);
    setActiveConversationId(id);
    setChatKey((key) => key + 1);
    setDrawerOpen(false);
  }

  function removeConversation(id: string) {
    deleteConversation(id);
    refreshConversations();
    if (activeConversationId === id) {
      newChat();
    }
    // Best-effort: the local delete above already reflects the user's
    // intent and has already updated the UI, so a failure here (backend
    // down, or the conversation was already gone server-side e.g. via
    // TTL purge) has nothing left for the user to react to.
    dashboardApi.deleteServerConversation(id).catch(() => {});
  }

  function openSettings() {
    setSettingsOpen(true);
    setDrawerOpen(false);
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

  // Lets code outside this component's own callback props (currently just
  // the settings modal's "delete all conversations") trigger a refresh
  // without prop-drilling a callback through the whole settings tree.
  useEffect(() => onConversationsChanged(refreshConversations), [refreshConversations]);

  // Closes the loop on the backend's TTL purge: removes locally any
  // conversation id the server reports as purged (never based on mere
  // absence - see the hook's own comment for why that distinction matters).
  useConversationSync(activeConversationId, refreshConversations);

  // The drawer is a mobile-only concept; force it closed when the
  // viewport crosses into the desktop breakpoint, where the sidebar is
  // always visible and the translate-x drawer classes are overridden.
  useEffect(() => {
    if (isDesktop) setDrawerOpen(false);
  }, [isDesktop]);

  useEffect(() => {
    if (!drawerOpen) return;
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setDrawerOpen(false);
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [drawerOpen]);

  return (
    <div className="flex h-dvh overflow-hidden bg-app">
      <Sidebar
        open={drawerOpen}
        conversations={conversations}
        activeConversationId={activeConversationId}
        onSelectConversation={selectConversation}
        onDeleteConversation={removeConversation}
        onNewChat={newChat}
        onOpenSettings={openSettings}
        backendUp={backendUp}
      />
      {drawerOpen && (
        <button
          type="button"
          aria-label="Kenar çubuğunu kapat"
          onClick={() => setDrawerOpen(false)}
          className="fixed inset-0 z-30 bg-black/50 md:hidden"
        />
      )}
      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        <MobileTopBar onOpenDrawer={() => setDrawerOpen(true)} onNewChat={newChat} />
        <main className="min-h-0 flex-1">
          <ChatView
            key={chatKey}
            conversationId={initialConversationId}
            onConversationId={handleConversationId}
          />
        </main>
      </div>
      <SettingsModal open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </div>
  );
}
