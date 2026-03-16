import React from "react";
import { useStreamingStore } from "#/stores/streaming-store";
import { ChatMessage } from "../../features/chat/chat-message";
import { cn } from "#/utils/utils";

interface StreamingMessageProps {
  /** The response_id that links streaming chunks together */
  responseId: string;
}

/**
 * Component that renders an in-progress streaming message.
 * Subscribes to the streaming store and updates as chunks arrive.
 */
export function StreamingMessage({ responseId }: StreamingMessageProps) {
  // Subscribe to streaming store for this specific response
  const content = useStreamingStore(
    (state) => state.activeStreams.get(responseId)?.content || "",
  );
  const isStreaming = useStreamingStore((state) =>
    state.isStreaming(responseId),
  );

  // Don't render if no content yet
  if (!content) {
    return null;
  }

  return (
    <div className={cn("relative", isStreaming && "streaming-message")}>
      <ChatMessage type="agent" message={content}>
        {/* Streaming indicator - animated cursor */}
        {isStreaming && (
          <span
            className="inline-block w-2 h-4 ml-1 bg-current animate-pulse"
            aria-label="Streaming in progress"
          />
        )}
      </ChatMessage>
    </div>
  );
}
