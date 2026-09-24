# Global Window Memory V1

Desktop chats retain their raw transcript in `ChatStore` JSON files and use the
stable chat ID as the key for a separate working-memory record in the canonical
Memory V1 SQLite database. Window memory is model-independent: changing the
selected Ollama model does not change its storage key or state.

Before inference, `WindowMemoryService` incrementally compacts messages older
than the bounded recent-message tail. The model receives canonical instructions,
relevant long-term memory, current-window memory, relevant compact summaries
from other windows, recent raw messages, and the current request. Raw messages
are never copied into the global long-term-memory table automatically.

`window_memories` is also the bounded cross-window registry. Its
`search_window_memories` API ranks at most a limited recent candidate set by
lexical overlap and returns only compact summaries, never other chats' raw
transcripts. A future semantic retriever can replace this ranking behind the
same interface without changing persistence or prompt assembly.

Assistant response actions are persisted in `response_feedback`. Thumbs-up is
feedback only. Remember runs the selected response through the existing
validated memory-candidate pipeline and writes deduplicated records to the
long-term `memories` table with response provenance.
