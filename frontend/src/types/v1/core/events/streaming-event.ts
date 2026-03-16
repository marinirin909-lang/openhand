import { BaseEvent } from "../base/event";

/**
 * Streaming text event - represents an incremental text chunk from LLM response.
 * Multiple streaming events with the same response_id form a complete message.
 */
export interface StreamingTextEvent extends BaseEvent {
  /**
   * Event kind identifier
   */
  kind: "StreamingTextEvent";

  /**
   * Links streaming chunks together - all chunks for the same response share this ID
   */
  response_id: string;

  /**
   * The incremental text content (delta, not cumulative)
   */
  content: string;

  /**
   * Incremental reasoning/thinking content (if provider supports it)
   */
  reasoning_content?: string | null;

  /**
   * Whether this is the final chunk in the stream
   */
  is_complete: boolean;
}
