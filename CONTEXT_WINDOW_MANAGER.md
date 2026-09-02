# Context Window Manager

Design document for `app/context_manager.py` — the module that guarantees every
LLM request fits inside a fixed token budget, no matter how much material the
user has dumped into a notebook.

## Why it exists

Language models have hard context limits, and API billing is per-token. A
student can paste five textbook chapters (hundreds of thousands of tokens) and
then ask "explain theorem 3.2". Naively stuffing everything into the prompt
fails on large notebooks and wastes money on small ones. The Context Window
Manager sits between the notebook's sources and the LLM call and produces a
prompt that **always** fits the budget.

## Pipeline

```
sources [(title, text)]
      │
      ▼
1. CHUNK        split each source into sentence-aligned chunks (~400 tokens)
                with 1-sentence overlap so context isn't lost at boundaries
      │
      ▼
2. MEASURE      estimate_tokens(text) ≈ len(text) / 4   (chars ÷ 4 heuristic)
      │         corpus_tokens_total = Σ chunk tokens
      ▼
3. FIT CHECK    corpus_budget = context_budget_tokens − max_output_tokens − 120
      │
      ├── total ≤ budget ──► use ALL chunks            fidelity: "full"
      │
      └── total > budget ──► SELECT phase              fidelity: "selected"
            ├── score every chunk against query+instruction:
            │       score = |chunk_words ∩ query_words| / √|chunk_words|
            │     (stopwords removed; √ normalization prevents long chunks
            │      from dominating purely by vocabulary size)
            ├── rank by (-score, original_order) — ties keep reading order
            ├── greedily pack chunks while used + tokens ≤ budget
            └── if one big chunk would fit ~92% of remaining space,
                truncate it head+tail instead of dropping it   → "truncated"
      │
      ▼
4. ASSEMBLE     re-sort selected chunks by original order (reading coherence),
                group consecutive chunks under "--- SOURCE: title ---" banners,
                wrap in system + user messages with anti-hallucination rules
```

## Truncation ladder

Fidelity levels reported in `build_messages().stats`:

| Fidelity     | Meaning                                              |
|--------------|------------------------------------------------------|
| `full`       | Entire corpus fits; nothing was touched             |
| `selected`   | Some whole chunks dropped by relevance ranking       |
| `truncated`  | Selection filled the budget *and* one chunk was cut mid-way |

Head+tail truncation keeps the opening and closing halves of an oversized chunk
(introductions and conclusions carry the most signal) and replaces the middle
with `[...middle truncated...]`.

## Public API

```python
estimate_tokens(text) -> int
significant_words(text) -> set[str]
chunk_text(text, title, chunk_tokens=400, overlap_sentences=1) -> list[Chunk]
relevance_score(chunk, query_words) -> float
head_tail_truncate(text, token_budget) -> str
build_messages(instruction, query, sources,
               budget_tokens=None, max_output_tokens=None) -> BuildResult
```

`BuildResult.messages` is a ready-to-send OpenAI-format chat payload;
`BuildResult.stats` is surfaced to the client (`used_context_tokens`,
`corpus_tokens_total`, `fidelity`, `dropped_chunks`, ...) so the UI can show
how much of the user's material actually reached the model.

## Configuration

| Env var                 | Default | Purpose                                   |
|-------------------------|---------|-------------------------------------------|
| `CONTEXT_BUDGET_TOKENS` | 6000    | Total prompt ceiling                      |
| `MAX_OUTPUT_TOKENS`     | 1200    | Reserved room for the model's reply       |
| `MAX_SOURCE_CHARS`      | 200000  | Per-source hard cap applied before chunking |

## Deliberate trade-offs

- **Chars÷4 token estimate** instead of a real tokenizer: zero dependencies and
  model-agnostic (works for any OpenAI-compatible endpoint). Accurate within
  ~10% for English, which is fine because budgets are conservative by design.
- **Keyword-overlap scoring** instead of embeddings: no vector store, no index
  to maintain, deterministic, and good enough for study material where the
  question usually shares vocabulary with the relevant section.
- **Sentence-boundary chunking** keeps prompts human-readable, which measurably
  helps smaller models follow citations.
