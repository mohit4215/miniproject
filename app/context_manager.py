"""Context Window Manager.

Builds LLM prompt payloads that always fit a fixed token budget by
chunking sources, scoring chunks against the query, and greedily packing
the highest-value content with head+tail truncation on overflow.
"""

import re
from dataclasses import dataclass, field

from .config import settings

_STOPWORDS = {
    "the", "and", "for", "are", "but", "not", "you", "all", "any", "can",
    "had", "her", "was", "one", "our", "out", "day", "get", "has", "him",
    "his", "how", "its", "new", "now", "old", "see", "two", "way", "who",
    "did", "this", "that", "with", "from", "they", "have", "will", "your",
    "what", "when", "which", "into", "than", "then", "them", "these",
    "there", "were", "would", "about", "could", "other", "such", "also",
}

_WORD_RE = re.compile(r"[a-z0-9]{3,}")
_SENT_RE = re.compile(r"(?<=[.!?])\s+")


def estimate_tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4)


def significant_words(text: str) -> set[str]:
    return {w for w in _WORD_RE.findall(text.lower()) if w not in _STOPWORDS}


@dataclass
class Chunk:
    title: str
    text: str
    order: int
    tokens: int = field(default=0)
    score: float = 0.0


@dataclass
class BuildResult:
    messages: list[dict]
    stats: dict


def chunk_text(text: str, title: str, chunk_tokens: int = 400, overlap_sentences: int = 1) -> list[Chunk]:
    sentences = [s for s in _SENT_RE.split(text.strip()) if s.strip()]
    if not sentences:
        return []
    chunks: list[Chunk] = []
    buf: list[str] = []
    buf_tokens = 0
    for i, sent in enumerate(sentences):
        st = estimate_tokens(sent)
        if buf and buf_tokens + st > chunk_tokens:
            chunks.append(Chunk(title=title, text=" ".join(buf), order=len(chunks)))
            tail = buf[-overlap_sentences:] if overlap_sentences else []
            buf = list(tail)
            buf_tokens = sum(estimate_tokens(s) for s in buf)
        buf.append(sent)
        buf_tokens += st
        if i == len(sentences) - 1:
            break
    if buf:
        chunks.append(Chunk(title=title, text=" ".join(buf), order=len(chunks)))
    for c in chunks:
        c.tokens = estimate_tokens(c.text)
    return chunks


def relevance_score(chunk: Chunk, query_words: set[str]) -> float:
    if not query_words:
        return 0.0
    words = significant_words(chunk.text)
    if not words:
        return 0.0
    overlap = len(words & query_words)
    return overlap / (len(words) ** 0.5)


def build_messages(
    instruction: str,
    query: str,
    sources: list[tuple[str, str]],
    budget_tokens: int | None = None,
    max_output_tokens: int | None = None,
) -> BuildResult:
    budget = budget_tokens or settings.context_budget_tokens
    output_reserve = max_output_tokens or settings.max_output_tokens
    overhead = 120
    corpus_budget = max(256, budget - output_reserve - overhead)

    all_chunks: list[Chunk] = []
    for idx, (title, content) in enumerate(sources):
        for ch in chunk_text(content[: settings.max_source_chars], title):
            ch.order += idx * 10000
            all_chunks.append(ch)

    total = sum(c.tokens for c in all_chunks)
    stats = {
        "sources": len(sources),
        "chunks": len(all_chunks),
        "corpus_tokens_total": total,
        "corpus_budget": corpus_budget,
        "fidelity": "full",
        "dropped_chunks": 0,
    }

    if total <= corpus_budget:
        selected = all_chunks
    else:
        qwords = significant_words(query + " " + instruction)
        for c in all_chunks:
            c.score = relevance_score(c, qwords)
        ranked = sorted(all_chunks, key=lambda c: (-c.score, c.order))
        selected: list[Chunk] = []
        used = 0
        for c in ranked:
            if used + c.tokens <= corpus_budget:
                selected.append(c)
                used += c.tokens
            elif used < corpus_budget * 0.92 and c.tokens > 80:
                keep = corpus_budget - used
                cut_text = head_tail_truncate(c.text, keep)
                trimmed = Chunk(title=c.title, text=cut_text, order=c.order)
                trimmed.tokens = estimate_tokens(cut_text)
                selected.append(trimmed)
                used += trimmed.tokens
                stats["fidelity"] = "truncated"
                break
        stats["fidelity"] = "truncated" if stats["fidelity"] == "truncated" else "selected"
        stats["dropped_chunks"] = len(all_chunks) - len(selected)
        selected.sort(key=lambda c: c.order)

    if not selected:
        joined = "(no source material available; answer from general knowledge)"
        used_tokens = 8
    else:
        parts = []
        current_title = None
        for c in selected:
            if c.title != current_title:
                parts.append(f"--- SOURCE: {c.title} ---")
                current_title = c.title
            parts.append(c.text)
        joined = "\n\n".join(parts)
        used_tokens = sum(c.tokens for c in selected)

    system_prompt = (
        "You are StudyPartner, an academic study assistant. "
        "Answer strictly from the provided SOURCES when they contain the answer; "
        "cite source titles inline like [Source: TITLE]. If sources are insufficient, say so "
        "and answer from general knowledge, clearly marked. Be concise and structured in Markdown."
    )
    user_prompt = (
        f"TASK:\n{instruction}\n\nQUERY:\n{query}\n\n"
        f"=== SOURCES ===\n{joined}\n=== END SOURCES ==="
    )
    stats.update({"used_context_tokens": used_tokens, "budget": budget})
    return BuildResult(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        stats=stats,
    )


def head_tail_truncate(text: str, token_budget: int) -> str:
    char_budget = token_budget * 4
    if len(text) <= char_budget:
        return text
    half = max(char_budget // 2 - 20, 100)
    return (
        text[:half].rsplit(" ", 1)[0]
        + "\n[...middle truncated...]\n"
        + text[-half:].lstrip()
    )
