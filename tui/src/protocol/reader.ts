import type { ProtocolEvent } from "./types.js";

export interface ProtocolReader {
  onEvent(handler: (event: ProtocolEvent) => void): () => void;
  onClose(handler: () => void): () => void;
  start(): void;
}
