import { useEffect } from "react";
import { useChat } from "../../hooks/useChat";
import { Composer } from "./Composer";
import { MessageList } from "./MessageList";

interface Props {
  conversationId: string | null;
  onConversationId: (id: string) => void;
}

export function ChatView({ conversationId, onConversationId }: Props) {
  const chat = useChat(conversationId, onConversationId);

  useEffect(() => {
    if (chat.conversationId) onConversationId(chat.conversationId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chat.conversationId]);

  return (
    <div className="flex h-full flex-col">
      <div className="flex-1 overflow-y-auto">
        <MessageList messages={chat.messages} livePhase={chat.livePhase} />
      </div>
      <Composer
        onSend={chat.send}
        disabled={chat.sending}
        awaitingConfirmation={chat.awaitingConfirmation}
        onApprove={chat.approve}
        onReject={chat.reject}
      />
    </div>
  );
}
