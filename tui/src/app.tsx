import { useCallback } from "react";
import { Box } from "ink";

import { ChatView } from "./components/ChatView.js";
import { InputArea } from "./components/InputArea.js";
import { StatusBar } from "./components/StatusBar.js";
import { useProtocolEvents } from "./hooks/useProtocolEvents.js";
import { useTurns } from "./hooks/useTurns.js";
import type { ProtocolReader } from "./protocol/reader.js";
import type { ProtocolWriter } from "./protocol/writer.js";

type AppProps = {
  onExitRequested: () => void;
  reader: ProtocolReader;
  writer: ProtocolWriter;
};

export function App({ onExitRequested, reader, writer }: AppProps) {
  const { events } = useProtocolEvents(reader);
  const { turns, threadId, setUserText } = useTurns(events);

  const isBusy = turns.some((turn) => turn.status === "active");

  // Find the active turn_id so we can stamp userText before sending.
  const activeTurnId = turns.find((t) => t.status === "active")?.turn_id;

  const handleSubmit = useCallback(
    (text: string): void => {
      if (activeTurnId !== undefined) {
        setUserText(activeTurnId, text);
      }
      writer.sendUserInput(text);
    },
    [activeTurnId, setUserText, writer],
  );

  const handleInterrupt = useCallback((): void => {
    writer.sendInterrupt();
  }, [writer]);

  return (
    <Box flexDirection="column">
      <Box flexDirection="column" flexGrow={1}>
        <ChatView turns={turns} />
      </Box>
      <InputArea
        disabled={isBusy}
        onExit={onExitRequested}
        onInterrupt={handleInterrupt}
        onSubmit={handleSubmit}
      />
      <StatusBar isBusy={isBusy} threadId={threadId} turnCount={turns.length} />
    </Box>
  );
}
