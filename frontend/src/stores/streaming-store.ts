import { create } from "zustand";

/**
 * Represents an in-progress streaming message being accumulated from chunks.
 */
interface StreamingMessage {
  /** Links chunks together - matches response_id from streaming events */
  responseId: string;
  /** Accumulated text content from all chunks */
  content: string;
  /** Accumulated reasoning/thinking content */
  reasoningContent: string;
  /** Whether the stream has completed */
  isComplete: boolean;
  /** Timestamp when streaming started */
  startedAt: number;
}

interface StreamingState {
  /** Map of response_id -> streaming message data */
  activeStreams: Map<string, StreamingMessage>;
}

interface StreamingActions {
  /**
   * Append a streaming chunk to the accumulated content.
   * Creates a new stream if one doesn't exist for this responseId.
   */
  appendChunk: (
    responseId: string,
    content: string,
    reasoningContent?: string | null,
  ) => void;

  /**
   * Mark a stream as complete. The stream data remains available until cleared.
   */
  completeStream: (responseId: string) => StreamingMessage | null;

  /**
   * Get the accumulated content for a stream.
   */
  getStreamContent: (responseId: string) => string;

  /**
   * Get the accumulated reasoning content for a stream.
   */
  getStreamReasoningContent: (responseId: string) => string;

  /**
   * Clear a stream from the store (call after final MessageEvent arrives).
   */
  clearStream: (responseId: string) => void;

  /**
   * Clear all streams (call on conversation change).
   */
  clearAllStreams: () => void;

  /**
   * Check if a stream is still in progress (not yet complete).
   */
  isStreaming: (responseId: string) => boolean;

  /**
   * Get all active (non-complete) stream IDs.
   */
  getActiveStreamIds: () => string[];
}

type StreamingStore = StreamingState & StreamingActions;

const initialState: StreamingState = {
  activeStreams: new Map(),
};

export const useStreamingStore = create<StreamingStore>((set, get) => ({
  ...initialState,

  appendChunk: (responseId, content, reasoningContent) =>
    set((state) => {
      const existing = state.activeStreams.get(responseId);
      const updated = new Map(state.activeStreams);

      updated.set(responseId, {
        responseId,
        content: (existing?.content || "") + content,
        reasoningContent:
          (existing?.reasoningContent || "") + (reasoningContent || ""),
        isComplete: false,
        startedAt: existing?.startedAt || Date.now(),
      });

      return { activeStreams: updated };
    }),

  completeStream: (responseId) => {
    const stream = get().activeStreams.get(responseId);
    if (stream) {
      set((state) => {
        const updated = new Map(state.activeStreams);
        updated.set(responseId, { ...stream, isComplete: true });
        return { activeStreams: updated };
      });
    }
    return stream || null;
  },

  getStreamContent: (responseId) =>
    get().activeStreams.get(responseId)?.content || "",

  getStreamReasoningContent: (responseId) =>
    get().activeStreams.get(responseId)?.reasoningContent || "",

  clearStream: (responseId) =>
    set((state) => {
      const updated = new Map(state.activeStreams);
      updated.delete(responseId);
      return { activeStreams: updated };
    }),

  clearAllStreams: () =>
    set(() => ({
      activeStreams: new Map(),
    })),

  isStreaming: (responseId) => {
    const stream = get().activeStreams.get(responseId);
    return stream ? !stream.isComplete : false;
  },

  getActiveStreamIds: () => {
    const streams = get().activeStreams;
    const activeIds: string[] = [];
    streams.forEach((stream, id) => {
      if (!stream.isComplete) {
        activeIds.push(id);
      }
    });
    return activeIds;
  },
}));
