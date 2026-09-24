# Global Window Memory V1

Desktop chats retain their raw transcript in `ChatStore` JSON files and use the
stable chat ID as the key for a separate working-memory record in the canonical
Memory V1 SQLite database. Window memory is model-independent: changing the
selected Ollama model does not change its storage key or state.

Before inference, `WindowMemoryService` incrementally compacts messages older
than the bounded recent-message tail. High-value explicit user state is also
written immediately to the `indexed_state` field of the same SQLite window
record, without promoting it to global long-term memory. The model receives canonical instructions,
relevant long-term memory, current-window memory, relevant compact summaries
from other windows, recent raw messages, and the current request. Raw messages
are never copied into the global long-term-memory table automatically.

`window_memories` is also the bounded cross-window registry. Its
`search_window_memories` API examines at most a limited recent candidate set,
requires meaningful semantic-token overlap and matching user-authored state,
then ranks by weighted relevance before recency. Unrelated windows and
assistant-only prose are excluded. Retrieval returns only bounded indexed state
or compact user summary lines, never other chats' raw transcripts or chat IDs.

Assistant response actions are persisted in `response_feedback`. Thumbs-up is
feedback only. Remember runs the selected response through the existing
validated memory-candidate pipeline and writes deduplicated records to the
long-term `memories` table with response provenance.
