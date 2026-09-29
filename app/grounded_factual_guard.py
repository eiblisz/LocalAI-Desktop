import re

from .request_semantics import identity_lookup_subject
from .text_normalization import (
    canonical_equal,
    canonical_match_text,
    matches_allowed_entity_surface,
)


class GroundedFactualGuardError(RuntimeError):
    pass


def _normalize(value):
    return canonical_match_text(value)


def _critical_literals(text):
    value = str(text or "")
    tokens = set()

    patterns = (
        r"https?://[^\s)\]>]+",
        r"(?<!\d)(?:1[0-9]{3}|20[0-9]{2})(?!\d)",
        r"\b\d{4}-\d{2}-\d{2}\b",
        r"\b\d{1,2}[./]\d{1,2}[./](?:19|20)\d{2}\b",
        r"(?<!\w)[$€£]\s*\d+(?:[.,]\d+)?(?:\s*(?:usd|eur|gbp|huf))?",
        r"\b\d+(?:[.,]\d+)?\s*(?:usd|eur|gbp|huf|btc|eth|%)\b",
        r"(?<![A-Za-z0-9])v?\d+\.\d+(?:\.\d+){0,2}(?:[-+][0-9A-Za-z.-]+)?(?![A-Za-z0-9])",
        r"\b[A-Za-z][A-Za-z0-9_-]*\d+(?:\.\d+){1,3}\b",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, value, flags=re.IGNORECASE):
            tokens.add(match.group(0).rstrip(".,;:"))

    # Quoted factual titles/names are critical literals too. This catches a
    # model inventing an album/book/work title even when it is a single word.
    for match in re.finditer(r'["“”„«»](.{2,120}?)["“”„«»]', value):
        quoted = " ".join(match.group(1).split()).strip(" .,:;!?")
        if quoted and re.search(r"[A-Za-zÁÉÍÓÖŐÚÜŰáéíóöőúüű]", quoted):
            tokens.add(quoted)

    # Retain one explicit proper-name span.  Do not manufacture overlapping
    # adjacent pairs: a person name followed by a title such as
    # "Arany János János Vitéz" used to create the false literal
    # "János János", which then made a valid answer fail closed.
    for match in re.finditer(
        r"\b[A-ZÁÉÍÓÖŐÚÜŰ][A-Za-zÁÉÍÓÖŐÚÜŰáéíóöőúüű-]{2,}"
        r"(?:\s+[A-ZÁÉÍÓÖŐÚÜŰ][A-Za-zÁÉÍÓÖŐÚÜŰáéíóöőúüű-]{2,})+\b",
        value,
    ):
        sequence = match.group(0)
        # Keep the complete supplied span for strict factual checking, but
        # never derive overlapping pairs from it.
        tokens.add(sequence)

    return tokens


def unsupported_grounded_literals(answer, authority_text):
    allowed_literals = _critical_literals(authority_text)
    allowed = {_normalize(item) for item in allowed_literals}
    authority_normalized = _normalize(authority_text)
    unsupported = []
    for item in _critical_literals(answer):
        normalized_item = _normalize(item)
        if normalized_item in allowed:
            continue
        if matches_allowed_entity_surface(item, allowed_literals):
            continue
        if (
            _looks_like_name_literal(item)
            and normalized_item
            and normalized_item in authority_normalized
        ):
            continue
        unsupported.append(item)
    return tuple(sorted(set(unsupported), key=str.casefold))


_TITLE_TOKEN = r"[A-ZÁÉÍÓÖŐÚÜŰ][A-Za-zÁÉÍÓÖŐÚÜŰáéíóöőúüű-]{1,}"


def _collapse_adjacent_proper_name_repetition(text):
    """Remove only adjacent duplicate title-case tokens, preserving spelling.

    This is a mechanical de-duplication, not entity correction.  It handles an
    LLM joining a person and a work title at their shared word boundary without
    attempting to infer either the person or the title.
    """
    cleaned = str(text or "")
    pattern = re.compile(
        rf"(?P<left>\b{_TITLE_TOKEN})\s+(?P<right>{_TITLE_TOKEN}\b)"
    )
    while True:
        changed = False

        def replace(match):
            nonlocal changed
            if canonical_equal(match.group("left"), match.group("right")):
                changed = True
                return match.group("left")
            return match.group(0)

        updated = pattern.sub(replace, cleaned)
        if not changed:
            return updated
        cleaned = updated


def _looks_like_name_literal(value):
    text = str(value or "").strip()
    if not text or re.search(r"https?://|\d|[$€£%]", text, flags=re.IGNORECASE):
        return False
    parts = [part for part in text.split() if part]
    return (
        len(parts) >= 2
        and all(part[0].isupper() for part in parts if part[0].isalpha())
    )


def _strip_unsupported_source_attributions(text, unsupported_literals):
    """
    Remove unsupported source/publication attribution wrappers without weakening
    factual checks for the answer itself.

    This is intentionally generic: it never recognizes specific publications or
    QA entities. Only proper-name literals already identified as unsupported are
    eligible, and only when they occur in a source-attribution shape.
    """
    cleaned = str(text or "")
    unsupported_names = [
        item for item in unsupported_literals
        if _looks_like_name_literal(item)
    ]

    for name in unsupported_names:
        escaped = re.escape(name)

        # Standalone source footer lines, e.g. "Forrás: Publication Name".
        cleaned = re.sub(
            rf"(?im)^[ \t]*(?:forrás|forras|source|quelle)\s*:\s*"
            rf"[^\r\n]*\b{escaped}\b[^\r\n]*(?:\r?\n|$)",
            "",
            cleaned,
        )

        # Prefix attribution, including variants such as
        # "A Publication egyik cikke szerint ..." / "Publication szerint ...".
        cleaned = re.sub(
            rf"(?i)(?<!\w)(?:a|az|the|der|die|das)?\s*"
            rf"{escaped}\b[^.!?\r\n]{{0,60}}?\b"
            rf"(?:szerint|according\s+to|laut)\b\s*[:,]?\s*",
            "",
            cleaned,
        )

        # English/German attribution where the marker comes first.
        cleaned = re.sub(
            rf"(?i)(?<!\w)(?:according\s+to|laut)\s+"
            rf"(?:a|az|the|der|die|das)?\s*{escaped}\b[:,]?\s*",
            "",
            cleaned,
        )

        # Bare parenthetical/bracketed source identity.
        cleaned = re.sub(
            rf"[\[(]\s*{escaped}\s*[\])]",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )

    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _canonicalize_identity_subject_expansion(
    text,
    user_prompt,
    unsupported_literals,
):
    """Remove an unsupported middle-name expansion of the requested identity.

    Models sometimes expand a two-part name from the question with an unverified
    middle name. That is not a reason to spend a second, slow model call: the
    user supplied the canonical subject spelling, and replacing only a matching
    first/last-name expansion preserves the grounded claim without inventing a
    fact. This remains generic and does not recognize any individual entity.
    """
    subject = identity_lookup_subject(user_prompt)
    subject_parts = re.findall(r"[^\W_]+", subject, flags=re.UNICODE)
    if len(subject_parts) < 2:
        return str(text or "")

    subject_first = _normalize(subject_parts[0])
    subject_last = _normalize(subject_parts[-1])
    cleaned = str(text or "")
    for literal in sorted(
        unsupported_literals or (),
        key=lambda value: len(str(value or "")),
        reverse=True,
    ):
        if not _looks_like_name_literal(literal):
            continue
        literal_parts = re.findall(
            r"[^\W_]+",
            str(literal),
            flags=re.UNICODE,
        )
        if (
            len(literal_parts) <= len(subject_parts)
            or _normalize(literal_parts[0]) != subject_first
            or _normalize(literal_parts[-1]) != subject_last
        ):
            continue
        cleaned = re.sub(
            rf"(?<!\w){re.escape(str(literal))}(?!\w)",
            subject,
            cleaned,
            flags=re.IGNORECASE,
        )
    return cleaned


def _remove_sentences_with_unsupported_literals(text, unsupported_literals):
    """Preserve supported long-form prose while removing risky sentences only."""
    normalized_literals = [
        canonical_match_text(item)
        for item in (unsupported_literals or ())
        if canonical_match_text(item)
    ]
    if not normalized_literals:
        return str(text or "").strip()

    output_blocks = []
    for block in re.split(r"\n\s*\n+", str(text or "").strip()):
        block = block.strip()
        if not block:
            continue
        sentences = [
            item.strip()
            for item in re.split(r"(?<=[.!?])\s+", block)
            if item.strip()
        ]
        kept = []
        for sentence in sentences:
            folded = canonical_match_text(sentence)
            if any(item in folded for item in normalized_literals):
                continue
            kept.append(sentence)
        if kept:
            output_blocks.append(" ".join(kept).strip())
    return "\n\n".join(output_blocks).strip()

def _grounded_sentence_units(text):
    """Return prose sentences with paragraph indexes; preserve heading-only blocks."""
    blocks = [
        block.strip()
        for block in re.split(r"\n\s*\n+|(?<=[.!?])\n(?=[A-ZÁÉÍÓÖŐÚÜŰ])", str(text or "").strip())
        if block.strip()
    ]
    headings = []
    units = []
    for block_index, block in enumerate(blocks):
        if (
            re.fullmatch(r"(?:#{1,6}\s+.+|\*\*.+\*\*|__.+__)", block)
            and not re.search(r"[.!?]\s*$", block)
        ):
            headings.append((block_index, block))
            continue
        parts = [
            item.strip()
            for item in re.split(
                r"(?<=[.!?])\s+(?=[A-ZÁÉÍÓÖŐÚÜŰ0-9„“\"(])",
                block,
            )
            if item.strip()
        ]
        if not parts:
            parts = [block]
        for sentence in parts:
            units.append({
                "id": len(units),
                "block": block_index,
                "text": sentence,
            })
    return blocks, headings, units


def _parse_sentence_support_gate(raw, units, authority_text):
    """Parse bounded KEEP/DROP judgments and verify KEEP evidence is source-bound."""
    judgments = {}
    unit_count = len(units)
    for raw_line in str(raw or "").replace("```", "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = re.match(
            r"^S?(\d+)\s*(?:\t|\||:|-)+\s*(KEEP|DROP)"
            r"(?:\s*(?:\t|\||:|-)+\s*(.*))?$",
            line,
            flags=re.IGNORECASE,
        )
        if not match:
            continue
        identifier = int(match.group(1))
        if identifier < 0 or identifier >= unit_count or identifier in judgments:
            return None
        status = match.group(2).upper()
        evidence = str(match.group(3) or "").strip().strip('"“”„')
        if status == "KEEP":
            if not _evidence_fragment_supports_sentence(
                units[identifier]["text"],
                evidence,
                authority_text,
            ):
                status = "DROP"
        judgments[identifier] = status
    if set(judgments) != set(range(unit_count)):
        return None
    return judgments


def _apply_sentence_support_gate(text, judgments):
    blocks, headings, units = _grounded_sentence_units(text)
    if not units:
        return str(text or "").strip()
    kept_by_block = {}
    for unit in units:
        if judgments.get(unit["id"]) == "KEEP":
            kept_by_block.setdefault(unit["block"], []).append(unit["text"])
    heading_map = {index: value for index, value in headings}
    rebuilt = []
    for index, _block in enumerate(blocks):
        if index in heading_map:
            rebuilt.append(heading_map[index])
            continue
        sentences = kept_by_block.get(index) or []
        if sentences:
            rebuilt.append(" ".join(sentences).strip())
    return "\n\n".join(rebuilt).strip()


_RELATION_MARKER_GROUPS = {
    "exclusive": ("only", "sole", "exclusively", "egyetlen", "egyeduli", "kizarolag", "einzig", "ausschliesslich"),
    "first": ("first", "earliest", "elso", "legkorabbi", "erste", "fruheste"),
    "last": ("last", "final", "latest", "utolso", "vegso", "legkesobbi", "letzte", "endgultig"),
    "father": ("father", "apja", "apa", "vater"),
    "mother": ("mother", "anyja", "anya", "mutter"),
    "uncle": ("uncle", "nagybacsi", "nagybáty", "onkel"),
    "aunt": ("aunt", "nagyneni", "nagynéni", "tante"),
    "son": ("son", "fia", "fiú", "sohn"),
    "daughter": ("daughter", "lanya", "lánya", "tochter"),
    "victory": ("victory", "won", "gyozelem", "gyozott", "sieg", "gewann"),
    "defeat": ("defeat", "lost", "vereseg", "vesztett", "niederlage", "verlor"),
    "surrender": ("surrender", "capitulat", "letette a fegyvert", "fegyverletetel", "kapitul", "ergab"),
    "leader": ("leader", "led", "vezeto", "vezette", "iranyitotta", "fuhrte"),
    "commander": ("commander", "commanded", "parancsnok", "parancsnoka", "befehlshaber"),
    "ally": ("ally", "allied", "szovetseges", "verbundet"),
    "support": ("support", "supported", "tamogat", "unterstutz"),
    "intervention": ("interven", "intervention", "beavatkoz", "intervention"),
    "ended": ("ended", "marked the end", "veget jelent", "vege lett", "endete", "beendete"),
    "caused": ("caused", "resulted in", "led to", "okoz", "eredmenyez", "vezetett", "fuhrte zu"),
    "basis": ("basis for", "foundation for", "alapja", "alapjava", "grundlage"),
}


def _relation_marker_classes(text):
    folded = canonical_match_text(text)
    found = set()
    for relation, markers in _RELATION_MARKER_GROUPS.items():
        if any(canonical_match_text(marker) in folded for marker in markers):
            found.add(relation)
    return found


def _strict_numeric_literals(text):
    value = str(text or "")
    patterns = (
        r"(?<!\d)(?:1[0-9]{3}|20[0-9]{2})(?!\d)",
        r"\b\d{4}-\d{2}-\d{2}\b",
        r"\b\d{1,2}[./]\d{1,2}[./](?:19|20)\d{2}\b",
        r"(?<!\w)[$€£]\s*\d+(?:[.,]\d+)?(?:\s*(?:usd|eur|gbp|huf))?",
        r"\b\d+(?:[.,]\d+)?\s*(?:usd|eur|gbp|huf|btc|eth|%)\b",
        r"(?<![A-Za-z0-9])v?\d+\.\d+(?:\.\d+){0,2}(?:[-+][0-9A-Za-z.-]+)?(?![A-Za-z0-9])",
    )
    result = []
    for pattern in patterns:
        result.extend(match.group(0).rstrip(".,;:") for match in re.finditer(pattern, value, flags=re.IGNORECASE))
    return tuple(dict.fromkeys(result))


def _evidence_fragment_supports_sentence(sentence, evidence, authority_text):
    evidence_text = str(evidence or "").strip()
    normalized_evidence = canonical_match_text(evidence_text)
    authority = canonical_match_text(authority_text)

    if len(normalized_evidence) < 16 or normalized_evidence not in authority:
        return False

    # Source URLs or a bibliography row are metadata, not factual evidence.
    prose_without_urls = re.sub(r"https?://\S+", " ", evidence_text, flags=re.IGNORECASE)
    prose_without_urls = re.sub(r"\[[^\]]+\]\([^\)]+\)", " ", prose_without_urls)
    if len(re.findall(r"[A-Za-zÁÉÍÓÖŐÚÜŰáéíóöőúüű]{2,}", prose_without_urls)) < 4:
        return False

    # Keep fragments focused enough that an unrelated relation elsewhere in a
    # whole source dump cannot certify the current sentence.
    if len(evidence_text) > 700:
        return False

    for literal in _strict_numeric_literals(sentence):
        if canonical_match_text(literal) not in normalized_evidence:
            return False

    # High-risk factual relations require the evidence fragment to explicitly
    # state the same relation class. This remains entity-agnostic and supports
    # Hungarian/English/German surface forms.
    sentence_relations = _relation_marker_classes(sentence)
    evidence_relations = _relation_marker_classes(evidence_text)
    if not sentence_relations.issubset(evidence_relations):
        return False

    return True


def _sentence_support_audit(
    client,
    model,
    user_prompt,
    draft,
    authority_text,
    *,
    output_budget=None,
    temperature=None,
    seed=None,
):
    """Gate long-form sentences against exact evidence fragments without rewriting."""
    _blocks, _headings, units = _grounded_sentence_units(draft)
    if not units:
        return None, None
    sentence_payload = "\n".join(
        f"S{unit['id']}: {unit['text']}"
        for unit in units
    )
    messages = [
        {
            "role": "system",
            "content": (
                "Audit each sentence independently against ONLY the authorized evidence. "
                "For every sentence id return exactly one line in this form: "
                "S0<TAB>KEEP<TAB>exact evidence fragment, or S0<TAB>DROP<TAB>-. "
                "KEEP only when the evidence directly supports every factual relation in "
                "the sentence. Mere co-occurrence of the same names is not support. Matching "
                "names or dates alone is not enough. DROP claims "
                "whose chronology, kinship, leadership, authorship, causation, institutional "
                "role, quantity, first/last status, or other relation is not directly supported. "
                "If support is missing, delete that sentence rather than guessing. "
                "The KEEP evidence fragment must be copied from AUTHORIZED EVIDENCE, not from "
                "the user request or draft. Copy a focused factual fragment, never a URL list, "
                "source list, bibliography row, or an entire source dump. For claims involving "
                "only/first/last/final status, family roles, leadership or command, alliance or "
                "support, intervention, victory/defeat/surrender, causation, institutional role, "
                "or an asserted ending, the copied fragment must explicitly state that same "
                "relation. Do not rewrite sentences and return no commentary."
            ),
        },
        {
            "role": "user",
            "content": (
                f"USER REQUEST (NOT EVIDENCE):\n{user_prompt}\n\n"
                f"AUTHORIZED EVIDENCE:\n{authority_text}\n\n"
                f"SENTENCES TO AUDIT:\n{sentence_payload}"
            ),
        },
    ]
    # The audit emits one verdict plus a source fragment per generated sentence.
    # A long-form answer can legitimately require more than the old fixed
    # 768-token ceiling even though the primary response budget is 2048.
    # Preserve the caller's smaller budget for short callers, but allow the
    # long-form contract to fund this bounded verification pass.
    audit_output_budget = min(2048, int(output_budget or 768))
    kwargs = {
        "model": model,
        "messages": messages,
        "num_predict": audit_output_budget,
        "call_phase": "factual_sentence_support_audit",
    }
    if temperature is not None:
        kwargs["temperature"] = float(temperature)
    if seed is not None:
        kwargs["seed"] = int(seed)
    while True:
        try:
            raw = client.chat_once(**kwargs).strip()
            break
        except TypeError as exc:
            unsupported = next(
                (
                    name
                    for name in ("num_predict", "temperature", "seed", "call_phase")
                    if name in str(exc) and name in kwargs
                ),
                "",
            )
            if not unsupported:
                raise
            kwargs.pop(unsupported)
    judgments = _parse_sentence_support_gate(
        raw,
        units,
        authority_text,
    )
    if judgments is None:
        return None, raw
    return _apply_sentence_support_gate(draft, judgments), raw

def guard_grounded_answer(
    client,
    model,
    user_prompt,
    answer,
    authority_text,
    *,
    trace=None,
    force_verify=False,
    literal_authority_text=None,
    repair_authority_text=None,
    prune_unsupported_sentences=False,
    strict_relation_audit=False,
    language_instruction="",
    output_budget=None,
    temperature=None,
    seed=None,
):
    draft = _collapse_adjacent_proper_name_repetition(str(answer or "").strip())
    literal_authority = str(literal_authority_text or authority_text or "")
    repair_authority = str(repair_authority_text or authority_text or "")
    unsupported = unsupported_grounded_literals(draft, literal_authority)
    if trace is not None:
        trace.add_metadata(
            factual_guard_force_verify=bool(force_verify),
            factual_guard_initial_unsupported_literals=", ".join(unsupported[:6]),
            factual_guard_remaining_unsupported_literals="",
            factual_guard_remaining_literals="",
            factual_guard_repair_status=(
                "pending" if (unsupported or force_verify) else "not_needed"
            ),
        )
    if unsupported and not force_verify:
        canonicalized = _canonicalize_identity_subject_expansion(
            draft,
            user_prompt,
            unsupported,
        )
        if canonicalized != draft:
            draft = canonicalized
            unsupported = unsupported_grounded_literals(draft, literal_authority)
    if not unsupported and not force_verify:
        return draft

    if unsupported and prune_unsupported_sentences:
        pruned_literals = unsupported
        pruned = _remove_sentences_with_unsupported_literals(
            draft,
            unsupported,
        )
        remaining_after_prune = unsupported_grounded_literals(
            pruned,
            literal_authority,
        )
        if pruned and not remaining_after_prune:
            draft = pruned
            unsupported = ()
            if trace is not None:
                trace.add_metadata(
                    factual_guard_repair_status=(
                        "deterministic_prune_pending_semantic_audit"
                        if force_verify
                        else "deterministic_prune"
                    ),
                    factual_guard_pruned_unsupported_literals=", ".join(
                        pruned_literals[:6]
                    ),
                    factual_guard_remaining_unsupported_literals="",
                    factual_guard_remaining_literals="",
                )
            if not force_verify:
                return draft

    audit_raw = None
    if strict_relation_audit:
        if trace is not None:
            trace.begin("factual_sentence_support_audit")
        gated, audit_raw = _sentence_support_audit(
            client,
            model,
            user_prompt,
            draft,
            repair_authority,
            output_budget=output_budget,
            temperature=temperature,
            seed=seed,
        )
        if trace is not None:
            trace.end(
                "factual_sentence_support_audit",
                factual_sentence_support_audit=(
                    "pass" if gated else "fallback_to_repair"
                ),
            )
        if gated:
            gated_remaining = unsupported_grounded_literals(
                gated,
                literal_authority,
            )
            if gated_remaining and prune_unsupported_sentences:
                gated = _remove_sentences_with_unsupported_literals(
                    gated,
                    gated_remaining,
                )
                gated_remaining = unsupported_grounded_literals(
                    gated,
                    literal_authority,
                )
            if gated and not gated_remaining:
                if trace is not None:
                    trace.add_metadata(
                        factual_guard_repair_status="pass_sentence_support_gate",
                        factual_guard_remaining_unsupported_literals="",
                        factual_guard_remaining_literals="",
                    )
                return gated

    if trace is not None:
        trace.begin("factual_guard_repair")

    repair_kwargs = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Repair the grounded answer using ONLY the authorized evidence supplied "
                    "below. Remove or replace factual literals that the evidence does not "
                    "support. Treat the user's premise as a claim to verify, not as authority. "
                    "If the evidence contradicts a person-work, person-event, date, year, "
                    "version, price, or current-fact premise, correct it explicitly. "
                    "If evidence is insufficient, state that briefly instead of guessing. "
                    "Treat explicit source titles and relevant-text identity cues as evidence too: "
                    "when a title or relevant-text field directly and consistently pairs a person "
                    "with a work, event, product, or other named subject, do not ignore that relation "
                    "merely because it is not repeated as a full prose sentence. "
                    "Answer the user's exact question immediately. Useful additional "
                    "context is allowed when it is supported by the authorized evidence. "
                    "Every added named work, track, album, person, date, number, price, "
                    "version, URL, or other concrete relation must be directly supported "
                    "and must stay bound to the same subject/entity in the evidence; do not "
                    "combine unrelated facts from different entities or sources. Keep the "
                    "answer concise by default, but do not remove useful evidence-backed "
                    "context solely to make it shorter. "
                    "Do not discuss source/publication titles unless the user asked about them. "
                    "Preserve proper-name spelling, diacritics, and token order from the most "
                    "directly relevant authorized evidence. If translated sources contain multiple "
                    "surface forms of the same person name, use the form conventional in the requested "
                    "answer language rather than inventing a new ordering. "
                    "Do not add any name, date, number, price, version, URL, or factual claim "
                    "that is absent from the authorized evidence or user request. "
                    "Do not expose verification protocol, sentence IDs, KEEP/DROP labels, "
                    "audit commentary, or reasoning about whether the evidence supports the draft. "
                    "Return only the user-facing repaired answer. "
                    + (
                        " For long-form factual synthesis, audit every sentence relation, not only "
                        "its names and dates. KEEP a sentence only when the authorized evidence "
                        "directly supports the relation it asserts. Mere co-occurrence of the same "
                        "names is not support. Do not infer military or political leadership, "
                        "chronology, causation, first/last/superlative status, institutional roles, "
                        "quantities, or responsibility from nearby evidence. If an exact relation "
                        "is not supported, delete that sentence rather than guessing or softening it."
                        if strict_relation_audit else ""
                    )
                    + (" " + str(language_instruction).strip()
                       if str(language_instruction or "").strip() else "")
                    + " Return only the repaired answer."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"USER REQUEST:\n{user_prompt}\n\n"
                    f"AUTHORIZED EVIDENCE:\n{repair_authority}\n\n"
                    f"DRAFT ANSWER:\n{draft}"
                ),
            },
        ],
    }
    repair_kwargs["call_phase"] = "factual_guard_repair"
    if output_budget is not None:
        repair_kwargs["num_predict"] = int(output_budget)
    if temperature is not None:
        repair_kwargs["temperature"] = float(temperature)
    if seed is not None:
        repair_kwargs["seed"] = int(seed)
    # A malformed sentence-audit response is internal protocol output, never
    # a candidate user answer. The old one-call fallback reused that raw text as
    # the repaired answer, which could leak S0/KEEP rows or audit commentary.
    # On protocol failure, run the normal grounded repair as a separate bounded
    # model call instead.
    if trace is not None and audit_raw is not None:
        trace.add_metadata(
            factual_sentence_support_audit_protocol=(
                "malformed_fallback_to_grounded_repair"
            ),
            factual_sentence_support_audit_raw_reused=False,
        )
    while True:
        try:
            repair = client.chat_once(**repair_kwargs).strip()
            break
        except TypeError as exc:
            unsupported = next(
                (
                    name
                    for name in ("num_predict", "temperature", "seed", "call_phase")
                    if name in str(exc) and name in repair_kwargs
                ),
                "",
            )
            if not unsupported:
                raise
            repair_kwargs.pop(unsupported)

    if trace is not None:
        trace.end("factual_guard_repair")

    if not repair:
        raise GroundedFactualGuardError(
            "Grounded factual repair returned an empty answer."
        )

    repair = _collapse_adjacent_proper_name_repetition(repair)
    remaining = unsupported_grounded_literals(repair, literal_authority)
    if trace is not None:
        trace.add_metadata(
            factual_guard_remaining_unsupported_literals=", ".join(remaining[:6]),
            factual_guard_remaining_literals=", ".join(remaining[:6]),
        )
    if remaining:
        sanitized = _strip_unsupported_source_attributions(repair, remaining)
        sanitized_remaining = unsupported_grounded_literals(
            sanitized,
            literal_authority,
        )
        if sanitized and not sanitized_remaining:
            if trace is not None:
                trace.add_metadata(
                    factual_guard_repair_status="pass_after_source_cleanup",
                    factual_guard_remaining_unsupported_literals="",
                    factual_guard_remaining_literals="",
                )
            return sanitized
        remaining = sanitized_remaining or remaining
        repair = sanitized if sanitized else repair

    if remaining and prune_unsupported_sentences:
        post_pruned = _remove_sentences_with_unsupported_literals(
            repair,
            remaining,
        )
        post_pruned_remaining = unsupported_grounded_literals(
            post_pruned,
            literal_authority,
        )
        if post_pruned and not post_pruned_remaining:
            if trace is not None:
                trace.add_metadata(
                    factual_guard_repair_status="pass_after_post_repair_prune",
                    factual_guard_post_repair_pruned_literals=", ".join(
                        remaining[:6]
                    ),
                    factual_guard_remaining_unsupported_literals="",
                    factual_guard_remaining_literals="",
                )
            return post_pruned

    if remaining:
        if trace is not None:
            trace.add_metadata(
                factual_guard_repair_status="unsupported_literals",
                factual_guard_remaining_unsupported_literals=", ".join(remaining[:6]),
                factual_guard_remaining_literals=", ".join(remaining[:6]),
            )
        raise GroundedFactualGuardError(
            "Grounded answer still contains unsupported factual literals: "
            + ", ".join(remaining[:6])
        )
    if trace is not None:
        trace.add_metadata(
            factual_guard_repair_status="pass",
            factual_guard_remaining_unsupported_literals="",
            factual_guard_remaining_literals="",
        )
    return repair
