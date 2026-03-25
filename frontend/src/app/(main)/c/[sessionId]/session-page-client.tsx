"use client";

import { ChatView } from "@/components/chat/chat-view";
import { useActiveSessionId } from "@/hooks/use-active-session-id";

export function SessionPageClient(_props: { sessionId: string }) {
  const resolvedSessionId = useActiveSessionId();

  if (!resolvedSessionId) return null;

  return <ChatView sessionId={resolvedSessionId} />;
}
