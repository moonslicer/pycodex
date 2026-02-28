import { Box } from "ink";

import { ChatView } from "./components/ChatView.js";
import { InputArea } from "./components/InputArea.js";
import { StatusBar } from "./components/StatusBar.js";
import { useProtocolEvents } from "./hooks/useProtocolEvents.js";
import { useTurns } from "./hooks/useTurns.js";
import type { ProtocolReader } from "./protocol/reader.js";
import type { ProtocolWriter } from "./protocol/writer.js";

type AppProps = {
  reader: ProtocolReader;
  writer: ProtocolWriter;
};

export function App({ reader, writer }: AppProps) {
  const { events } = useProtocolEvents(reader);
  const { turns, threadId } = useTurns(events);

  const isBusy = turns.some((turn) => turn.status === "active");

  function handleSubmit(text: string): void {
    writer.sendUserInput(text);
  }

  function handleInterrupt(): void {
    writer.sendInterrupt();
  }

  return (
    <Box flexDirection="column">
      <Box flexDirection="column" flexGrow={1}>
        <ChatView turns={turns} />
      </Box>
      <InputArea
        disabled={isBusy}
        onInterrupt={handleInterrupt}
        onSubmit={handleSubmit}
      />
      <StatusBar isBusy={isBusy} threadId={threadId} turnCount={turns.length} />
    </Box>
  );
}
