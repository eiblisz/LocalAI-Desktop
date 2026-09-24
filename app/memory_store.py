import re
import sqlite3
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path

from .config import MEMORY_CANONICAL_DIR
from .text_normalization import canonical_match_text


DEFAULT_MEMORY_DB = MEMORY_CANONICAL_DIR / "memory.sqlite3"

ALLOWED_CATEGORIES = {
    "USER_PROFILE",
    "PROJECT",
    "PREFERENCE",
    "RULE",
    "LESSON",
    "WORKING",
}

ALLOWED_IMPORTANCE = {
    "IGNORE",
    "SESSION_ONLY",
    "REMEMBER",
    "IMPORTANT",
    "PINNED",
}

ALLOWED_STATUS = {
    "active",
    "superseded",
    "archived",
    "deleted",
}

_SECRET_KEY_TOKENS = {
    "api_key",
    "apikey",
    "password",
    "passwd",
    "pwd",
    "secret",
    "token",
    "access_token",
    "refresh_token",
    "private_key",
    "privatekey",
    "otp",
    "one_time_password",
    "auth_cookie",
    "cookie",
    "session_cookie",
    "pin",
    "cvv",
    "cvc",
    "iban",
    "bank_account",
    "banking_secret",
}

_SECRET_VALUE_PATTERNS = [
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |)?PRIVATE KEY-----", re.IGNORECASE),
    re.compile(r"\b(?:sk|pk)_[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b", re.IGNORECASE),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{16,}\b", re.IGNORECASE),
    re.compile(r"\b(?:otp|one[- ]?time password)\s*[:=]\s*\d{4,10}\b", re.IGNORECASE),
]


def _now():
    return datetime.now().isoformat(timespec="seconds")


def _clean(value):
    return " ".join(str(value or "").strip().split())


def _normalize_key(value):
    return re.sub(r"[^a-z0-9]+", "_", _clean(value).lower()).strip("_")


def secret_memory_reason(*, key="", value="", subject=""):
    normalized_key = _normalize_key(key)
    normalized_subject = _normalize_key(subject)

    for token in _SECRET_KEY_TOKENS:
        if token == normalized_key or token in normalized_key.split("_"):
            return f"secret key field: {token}"
        if token == normalized_subject or token in normalized_subject.split("_"):
            return f"secret subject field: {token}"

    text = str(value or "")
    for pattern in _SECRET_VALUE_PATTERNS:
        if pattern.search(text):
            return "secret value pattern"

    return ""


def is_secret_memory_candidate(*, key="", value="", subject=""):
    return bool(secret_memory_reason(key=key, value=value, subject=subject))


class MemoryStore:
    def __init__(self, path: Path = DEFAULT_MEMORY_DB):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self):
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    category TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    importance TEXT NOT NULL,
                    confidence REAL NOT NULL DEFAULT 1.0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_used_at TEXT,
                    source_chat_id TEXT,
                    status TEXT NOT NULL DEFAULT 'active',
                    supersedes_id TEXT,
                    FOREIGN KEY (supersedes_id) REFERENCES memories(id)
                );

                CREATE INDEX IF NOT EXISTS idx_memories_scope_status
                ON memories(scope, status);

                CREATE INDEX IF NOT EXISTS idx_memories_lookup
                ON memories(category, scope, subject, key, status);

                CREATE TABLE IF NOT EXISTS memory_sources (
                    id TEXT PRIMARY KEY,
                    memory_id TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_ref TEXT,
                    excerpt TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS memory_links (
                    id TEXT PRIMARY KEY,
                    memory_id TEXT NOT NULL,
                    related_memory_id TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE,
                    FOREIGN KEY (related_memory_id) REFERENCES memories(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS memory_conflicts (
                    id TEXT PRIMARY KEY,
                    memory_id TEXT NOT NULL,
                    conflicting_memory_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'open',
                    resolution TEXT,
                    created_at TEXT NOT NULL,
                    resolved_at TEXT,
                    FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE,
                    FOREIGN KEY (conflicting_memory_id) REFERENCES memories(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS lessons (
                    id TEXT PRIMARY KEY,
                    scope TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    rule TEXT NOT NULL,
                    importance TEXT NOT NULL DEFAULT 'REMEMBER',
                    confidence REAL NOT NULL DEFAULT 1.0,
                    source_chat_id TEXT,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS window_memories (
                    chat_id TEXT PRIMARY KEY,
                    summary TEXT NOT NULL,
                    compacted_message_count INTEGER NOT NULL DEFAULT 0,
                    source_message_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_window_memories_updated
                ON window_memories(updated_at DESC);

                CREATE TABLE IF NOT EXISTS response_feedback (
                    chat_id TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    feedback_type TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (chat_id, message_id, feedback_type)
                );

                CREATE INDEX IF NOT EXISTS idx_response_feedback_chat
                ON response_feedback(chat_id, message_id);
                """
            )
            window_columns = {
                row["name"]
                for row in db.execute("PRAGMA table_info(window_memories)").fetchall()
            }
            if "indexed_state" not in window_columns:
                db.execute(
                    "ALTER TABLE window_memories "
                    "ADD COLUMN indexed_state TEXT NOT NULL DEFAULT ''"
                )

    @staticmethod
    def _validate_enum(name, value, allowed):
        if value not in allowed:
            raise ValueError(f"invalid {name}: {value}")

    @staticmethod
    def _row_to_dict(row):
        return dict(row) if row is not None else None

    def add_memory(
        self,
        *,
        category,
        scope,
        subject,
        key,
        value,
        importance="REMEMBER",
        confidence=1.0,
        source_chat_id=None,
        supersedes_id=None,
    ):
        category = _clean(category).upper()
        scope = _clean(scope)
        subject = _clean(subject)
        key = _clean(key)
        value = _clean(value)
        importance = _clean(importance).upper()

        self._validate_enum("category", category, ALLOWED_CATEGORIES)
        self._validate_enum("importance", importance, ALLOWED_IMPORTANCE)

        if not scope or not subject or not key or not value:
            raise ValueError("scope, subject, key, and value are required")

        reason = secret_memory_reason(key=key, value=value, subject=subject)
        if reason:
            raise ValueError(f"secret memory rejected: {reason}")

        confidence = float(confidence)
        if confidence < 0.0 or confidence > 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")

        memory_id = uuid.uuid4().hex
        now = _now()

        with self._connect() as db:
            if supersedes_id:
                current = db.execute(
                    "SELECT id, status FROM memories WHERE id = ?",
                    (supersedes_id,),
                ).fetchone()
                if current is None:
                    raise KeyError(supersedes_id)
                db.execute(
                    "UPDATE memories SET status = 'superseded', updated_at = ? WHERE id = ?",
                    (now, supersedes_id),
                )

            db.execute(
                """
                INSERT INTO memories (
                    id, category, scope, subject, key, value, importance,
                    confidence, created_at, updated_at, last_used_at,
                    source_chat_id, status, supersedes_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, 'active', ?)
                """,
                (
                    memory_id,
                    category,
                    scope,
                    subject,
                    key,
                    value,
                    importance,
                    confidence,
                    now,
                    now,
                    source_chat_id,
                    supersedes_id,
                ),
            )

        return self.get_memory(memory_id)

    def remember_explicit(
        self,
        *,
        category,
        scope,
        subject,
        key,
        value,
        source_chat_id=None,
        source_excerpt=None,
        source_type="explicit_user",
        source_ref=None,
        importance="IMPORTANT",
        confidence=1.0,
    ):
        """Persist an explicit user memory idempotently with provenance."""
        category = _clean(category).upper()
        scope = _clean(scope)
        subject = _clean(subject)
        key = _clean(key)
        value = _clean(value)

        self._validate_enum("category", category, ALLOWED_CATEGORIES)

        with self._connect() as db:
            existing = db.execute(
                """
                SELECT *
                FROM memories
                WHERE category = ?
                  AND scope = ?
                  AND subject = ?
                  AND key = ?
                  AND status = 'active'
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (category, scope, subject, key),
            ).fetchone()

        if existing is not None and _clean(existing["value"]) == value:
            memory = self._row_to_dict(existing)
            self._record_source(
                memory["id"],
                source_type=source_type,
                source_ref=source_ref or source_chat_id,
                excerpt=source_excerpt,
            )
            return memory

        memory = self.add_memory(
            category=category,
            scope=scope,
            subject=subject,
            key=key,
            value=value,
            importance=importance,
            confidence=confidence,
            source_chat_id=source_chat_id,
            supersedes_id=(existing["id"] if existing is not None else None),
        )

        self._record_source(
            memory["id"],
            source_type=source_type,
            source_ref=source_ref or source_chat_id,
            excerpt=source_excerpt,
        )
        return memory

    def _record_source(
        self,
        memory_id,
        *,
        source_type,
        source_ref=None,
        excerpt=None,
    ):
        now = _now()
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO memory_sources (
                    id, memory_id, source_type, source_ref, excerpt, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid.uuid4().hex,
                    memory_id,
                    _clean(source_type),
                    _clean(source_ref) or None,
                    _clean(excerpt) or None,
                    now,
                ),
            )

    def list_memory_sources(self, memory_id):
        self.get_memory(memory_id)
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT *
                FROM memory_sources
                WHERE memory_id = ?
                ORDER BY created_at ASC
                """,
                (memory_id,),
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def get_memory(self, memory_id):
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM memories WHERE id = ?",
                (memory_id,),
            ).fetchone()
        if row is None:
            raise KeyError(memory_id)
        return self._row_to_dict(row)

    def list_memories(
        self,
        *,
        scope=None,
        category=None,
        statuses=("active",),
        include_session_only=True,
    ):
        clauses = []
        params = []

        if scope is not None:
            clauses.append("scope = ?")
            params.append(_clean(scope))

        if category is not None:
            category = _clean(category).upper()
            self._validate_enum("category", category, ALLOWED_CATEGORIES)
            clauses.append("category = ?")
            params.append(category)

        statuses = tuple(statuses or ())
        for status in statuses:
            self._validate_enum("status", status, ALLOWED_STATUS)
        if statuses:
            placeholders = ",".join("?" for _ in statuses)
            clauses.append(f"status IN ({placeholders})")
            params.extend(statuses)

        if not include_session_only:
            clauses.append("importance != 'SESSION_ONLY'")

        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        query = (
            "SELECT * FROM memories"
            + where
            + " ORDER BY CASE importance "
              "WHEN 'PINNED' THEN 5 WHEN 'IMPORTANT' THEN 4 "
              "WHEN 'REMEMBER' THEN 3 WHEN 'SESSION_ONLY' THEN 2 ELSE 1 END DESC, "
              "updated_at DESC"
        )

        with self._connect() as db:
            rows = db.execute(query, params).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def retrieve_memories(self, query, *, scope=None, limit=8):
        """Return a bounded set of active long-term memories relevant to query."""
        query = _clean(query)
        if not query:
            return []

        limit = int(limit)
        if limit < 1:
            return []

        query_tokens = set(re.findall(r"[a-z0-9_]+", query.lower()))
        candidates = self.list_memories(
            scope=scope,
            statuses=("active",),
            include_session_only=False,
        )

        importance_weight = {
            "PINNED": 40,
            "IMPORTANT": 20,
            "REMEMBER": 10,
        }

        ranked = []
        for memory in candidates:
            if memory.get("importance") == "IGNORE":
                continue

            searchable = " ".join(
                str(memory.get(field, ""))
                for field in ("category", "scope", "subject", "key", "value")
            ).lower()
            memory_tokens = set(re.findall(r"[a-z0-9_]+", searchable))
            overlap = len(query_tokens & memory_tokens)

            # PINNED memories are always eligible as durable global context.
            if overlap == 0 and memory.get("importance") != "PINNED":
                continue

            score = (
                overlap * 100
                + importance_weight.get(memory.get("importance"), 0)
                + int(float(memory.get("confidence", 0.0)) * 10)
            )
            ranked.append((score, memory.get("updated_at", ""), memory))

        ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [item[2] for item in ranked[:limit]]

    def archive_memory(self, memory_id):
        return self._set_status(memory_id, "archived")

    def delete_memory(self, memory_id):
        return self._set_status(memory_id, "deleted")

    def _set_status(self, memory_id, status):
        self._validate_enum("status", status, ALLOWED_STATUS)
        now = _now()
        with self._connect() as db:
            cursor = db.execute(
                "UPDATE memories SET status = ?, updated_at = ? WHERE id = ?",
                (status, now, memory_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(memory_id)
        return self.get_memory(memory_id)

    def set_importance(self, memory_id, importance):
        importance = _clean(importance).upper()
        self._validate_enum("importance", importance, ALLOWED_IMPORTANCE)
        now = _now()
        with self._connect() as db:
            cursor = db.execute(
                "UPDATE memories SET importance = ?, updated_at = ? WHERE id = ?",
                (importance, now, memory_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(memory_id)
        return self.get_memory(memory_id)

    def revise_memory(
        self,
        memory_id,
        *,
        category=None,
        scope=None,
        subject=None,
        key=None,
        value=None,
        importance=None,
        confidence=None,
        source_type="memory_ui",
        source_ref=None,
        source_excerpt=None,
    ):
        current = self.get_memory(memory_id)
        if current.get("status") != "active":
            raise ValueError("only active memories can be revised")

        next_category = (
            _clean(category).upper()
            if category is not None
            else current["category"]
        )
        next_scope = _clean(scope) if scope is not None else current["scope"]
        next_subject = (
            _clean(subject) if subject is not None else current["subject"]
        )
        next_key = _clean(key) if key is not None else current["key"]
        next_value = _clean(value) if value is not None else current["value"]
        next_importance = (
            _clean(importance).upper()
            if importance is not None
            else current["importance"]
        )
        next_confidence = (
            float(confidence)
            if confidence is not None
            else float(current["confidence"])
        )

        comparable = {
            "category": next_category,
            "scope": next_scope,
            "subject": next_subject,
            "key": next_key,
            "value": next_value,
            "importance": next_importance,
            "confidence": next_confidence,
        }
        if all(
            comparable[field] == (
                float(current[field])
                if field == "confidence"
                else current[field]
            )
            for field in comparable
        ):
            return current

        revised = self.add_memory(
            category=next_category,
            scope=next_scope,
            subject=next_subject,
            key=next_key,
            value=next_value,
            importance=next_importance,
            confidence=next_confidence,
            source_chat_id=current.get("source_chat_id"),
            supersedes_id=memory_id,
        )
        self._record_source(
            revised["id"],
            source_type=source_type,
            source_ref=source_ref or memory_id,
            excerpt=source_excerpt or "Revised from Memory UI",
        )
        return revised

    def memory_lineage(self, memory_id):
        current = self.get_memory(memory_id)

        ancestors = []
        seen = {current["id"]}
        cursor = current
        while cursor.get("supersedes_id"):
            previous_id = cursor["supersedes_id"]
            if previous_id in seen:
                break
            previous = self.get_memory(previous_id)
            ancestors.append(previous)
            seen.add(previous_id)
            cursor = previous
        ancestors.reverse()

        descendants = []
        cursor_id = current["id"]
        while True:
            with self._connect() as db:
                row = db.execute(
                    """
                    SELECT *
                    FROM memories
                    WHERE supersedes_id = ?
                    ORDER BY created_at ASC
                    LIMIT 1
                    """,
                    (cursor_id,),
                ).fetchone()
            if row is None:
                break
            item = self._row_to_dict(row)
            if item["id"] in seen:
                break
            descendants.append(item)
            seen.add(item["id"])
            cursor_id = item["id"]

        return ancestors + [current] + descendants

    def mark_used(self, memory_id):
        now = _now()
        with self._connect() as db:
            cursor = db.execute(
                "UPDATE memories SET last_used_at = ?, updated_at = ? WHERE id = ?",
                (now, now, memory_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(memory_id)
        return self.get_memory(memory_id)

    def get_window_memory(self, chat_id):
        chat_id = _clean(chat_id)
        if not chat_id:
            return None
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM window_memories WHERE chat_id = ?",
                (chat_id,),
            ).fetchone()
        return self._row_to_dict(row)

    def upsert_window_memory(
        self,
        chat_id,
        summary,
        *,
        compacted_message_count,
        source_message_count,
    ):
        chat_id = _clean(chat_id)
        summary = str(summary or "").strip()
        if not chat_id:
            raise ValueError("chat_id is required")
        if not summary:
            raise ValueError("window memory summary is required")

        now = _now()
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO window_memories (
                    chat_id, summary, compacted_message_count,
                    source_message_count, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    summary = excluded.summary,
                    compacted_message_count = excluded.compacted_message_count,
                    source_message_count = excluded.source_message_count,
                    updated_at = excluded.updated_at
                """,
                (
                    chat_id,
                    summary,
                    max(0, int(compacted_message_count)),
                    max(0, int(source_message_count)),
                    now,
                    now,
                ),
            )
        return self.get_window_memory(chat_id)

    def upsert_window_indexed_state(
        self,
        chat_id,
        indexed_state,
        *,
        source_message_count,
    ):
        chat_id = _clean(chat_id)
        indexed_state = str(indexed_state or "").strip()
        if not chat_id:
            raise ValueError("chat_id is required")
        if not indexed_state:
            raise ValueError("indexed window state is required")

        now = _now()
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO window_memories (
                    chat_id, summary, indexed_state, compacted_message_count,
                    source_message_count, created_at, updated_at
                ) VALUES (?, '', ?, 0, ?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    indexed_state = excluded.indexed_state,
                    source_message_count = MAX(
                        window_memories.source_message_count,
                        excluded.source_message_count
                    ),
                    updated_at = excluded.updated_at
                """,
                (
                    chat_id,
                    indexed_state,
                    max(0, int(source_message_count)),
                    now,
                    now,
                ),
            )
        return self.get_window_memory(chat_id)

    def list_window_memories(self, *, exclude_chat_id=None, limit=50):
        limit = max(0, min(int(limit), 200))
        if not limit:
            return []
        params = []
        where = ""
        if exclude_chat_id:
            where = " WHERE chat_id != ?"
            params.append(_clean(exclude_chat_id))
        params.append(limit)
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT * FROM window_memories
                """
                + where
                + " ORDER BY updated_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def search_window_memories(
        self,
        query,
        *,
        exclude_chat_id=None,
        limit=3,
        candidate_limit=50,
    ):
        ignored = {
            "the", "a", "an", "is", "was", "what", "which", "given", "other",
            "another", "conversation", "chat", "this", "in", "about",
            "mi", "mit", "volt", "van", "egy", "masik", "masikban", "ebben",
            "beszelgetes", "beszelgetesben", "megadott", "kapcsolatban",
            "der", "die", "das", "was", "ist", "war", "anderen", "gesprach",
        }
        query_tokens = {
            token
            for token in canonical_match_text(query).split()
            if len(token) >= 3 and token not in ignored
        }
        if not query_tokens or int(limit) < 1:
            return []
        candidates = self.list_window_memories(
            exclude_chat_id=exclude_chat_id,
            limit=candidate_limit,
        )
        document_frequency = Counter()
        tokenized = []
        for item in candidates:
            content = "\n".join(
                part
                for part in (
                    str(item.get("indexed_state") or ""),
                    str(item.get("summary") or ""),
                )
                if part
            )
            content_tokens = {
                token
                for token in canonical_match_text(content).split()
                if len(token) >= 3 and token not in ignored
            }
            tokenized.append((item, content, content_tokens))
            document_frequency.update(content_tokens)

        ranked = []
        candidate_count = max(1, len(tokenized))
        for item, content, content_tokens in tokenized:
            if is_secret_memory_candidate(
                key=content,
                value=content,
                subject=content,
            ):
                continue
            overlap_tokens = query_tokens & content_tokens
            if len(overlap_tokens) < 2:
                continue
            weighted_overlap = sum(
                1.0 + (candidate_count / max(1, document_frequency[token]))
                for token in overlap_tokens
            )
            coverage = len(overlap_tokens) / max(1, len(query_tokens))
            user_lines = "\n".join(
                line for line in content.splitlines()
                if line.strip().casefold().startswith("- user:")
            )
            user_tokens = set(canonical_match_text(user_lines).split())
            user_overlap = len(query_tokens & user_tokens)
            if user_overlap < 1:
                continue
            score = weighted_overlap + (coverage * 4.0) + (user_overlap * 2.0)
            if score < 6.0:
                continue
            ranked.append((score, user_overlap, item.get("updated_at", ""), item))
        ranked.sort(key=lambda entry: (entry[0], entry[1], entry[2]), reverse=True)
        return [entry[3] for entry in ranked[: max(0, min(int(limit), 10))]]

    def set_response_feedback(self, chat_id, message_id, feedback_type, *, active=True):
        chat_id = _clean(chat_id)
        message_id = _clean(message_id)
        feedback_type = _clean(feedback_type).lower()
        if not chat_id or not message_id:
            raise ValueError("chat_id and message_id are required")
        if feedback_type not in {"thumbs_up", "remember"}:
            raise ValueError("invalid response feedback type")
        now = _now()
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO response_feedback (
                    chat_id, message_id, feedback_type, active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(chat_id, message_id, feedback_type) DO UPDATE SET
                    active = excluded.active,
                    updated_at = excluded.updated_at
                """,
                (chat_id, message_id, feedback_type, bool(active), now, now),
            )
        return self.get_response_feedback(chat_id, message_id)

    def get_response_feedback(self, chat_id, message_id):
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT feedback_type, active
                FROM response_feedback
                WHERE chat_id = ? AND message_id = ?
                """,
                (_clean(chat_id), _clean(message_id)),
            ).fetchall()
        return {
            row["feedback_type"]: bool(row["active"])
            for row in rows
        }
