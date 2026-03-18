# Search Input — Proposed Improvements

Tracking doc for improving the FTS search logic in `build_fts_query_2()` in `app.py`.

---

## Current Bugs

- [x] **AND doesn't actually AND** — all terms go into `disjuncts` (OR) regardless of operator
- [x] **NOT is completely ignored** — just prints a debug warning and skips the term
- [x] **`escape_fts_query_string` breaks wildcards** — escapes `*` but wildcards need unescaped `*` in JSON query objects
- [x] **Field names get lowercased and break** — `processId` → `processid` won't match the index; `mainType` → `maintype` fails too
- [x] **processId wildcard fallback is useless** — it's a numeric field in the index, so `match`/`wildcard` on it silently returns nothing
- [x] **Massive code duplication** — same field:value and wildcard logic copy-pasted across 3 branches (boolean, field:value, simple)

---

## Priority 1 — Fix Correctness

### Fix Boolean Semantics
- AND terms → `conjuncts` (all required)
- OR terms → `disjuncts` (any match)
- NOT / `-term` → `must_not.disjuncts` (exclusion)
- Default behavior: space-separated = AND (users expect `push error` to mean both)

### Add Field Alias Map
Map user input to actual index field names:

```python
FIELD_ALIASES = {
    "rawlog": "rawLog",
    "type": "type",
    "maintype": "mainType",
    "processid": "processId",
    "pid": "processId",
    "error": "error",
    "dt": "dt",
    "dtepoch": "dtEpoch",
}
```

Unknown fields should return a validation error instead of silently generating a useless query.

### Remove `escape_fts_query_string`
The function is designed for query-string syntax, but `build_fts_query_2()` builds JSON query objects where `json.dumps()` handles escaping. The function currently harms wildcard behavior.

### Validate Numeric Fields
`processId` is numeric in the index. Reject invalid input with a clear message:
- `processId:123` → numeric range query (valid)
- `processId:12*` → reject with "processId must be numeric"
- Future: support `processId:100..200` or `processId:>100`

---

## Priority 2 — Better UX

### Support Quoted Phrases
`"connection refused"` → `match_phrase` query.

> **Note:** Phrase queries may require term vectors enabled on text fields in the FTS index. Verify `rawLog`, `type`, and `mainType` support this before shipping.

### Support Negation with `-`
`-healthcheck` or `NOT healthcheck` → exclude from results.

### Trailing `*` as Prefix Query
`retry*` → `prefix` query (faster than `wildcard`).

Consider rejecting leading/infix wildcards (`*foo`, `f*o`) for now — they can be slow and produce surprising results.

### Error Field Shortcuts
- `error:true` / `error:yes` / `error:1` → `{"field": "error", "bool": true}`
- `error:false` / `error:no` / `error:0` → `{"field": "error", "bool": false}`
- Bare `error` or `errors` → filter for `error=true` docs (existing behavior, keep it)

---

## Priority 3 — Code Cleanup

- [x] Delete dead `build_fts_query()` function (line 70–85)
- [x] Delete `escape_search_term()` function (line 65–68) — unused
- [x] One `build_leaf(field, value, is_phrase=False)` function replaces 3 duplicated branches
- [x] `build_fts_query_2()` returns a Python dict, only `json.dumps()` at the call site
- [x] Turn off `"explain": True` unless `debug` is enabled
- [ ] Don't request `"fields": ["*"]` unless the endpoint needs all fields

---

## Target Search Syntax

| Input | Behavior |
|---|---|
| `push error` | push AND error in rawLog |
| `push OR error` | either term matches |
| `-healthcheck` | exclude healthcheck |
| `NOT healthcheck` | exclude healthcheck |
| `"connection refused"` | exact phrase match |
| `type:Sync` | field-specific match |
| `mainType:BLIP` | field-specific match |
| `pid:1047` | processId numeric match (alias) |
| `processId:1047` | processId numeric match |
| `error:true` | boolean filter |
| `retry*` | prefix search |
| `type:Sync AND error:true` | combined filters |
| `push AND error -healthcheck` | push + error, excluding healthcheck |

---

## Refactored Architecture

### Step 1: Tokenize
Parse user input into tokens, preserving quoted phrases and operators:
```
"push AND error -healthcheck" → ["push", "AND", "error", "-healthcheck"]
"type:Sync \"connection refused\"" → ["type:Sync", "connection refused" (phrase)]
```

### Step 2: Build Leaf Clauses
One function decides query type based on field + value:

```python
def build_leaf(field, value, is_phrase=False):
    if field == "processId":
        # numeric range query
    elif field == "error":
        # boolean query
    elif is_phrase:
        # match_phrase query
    elif value.endswith("*") and value.count("*") == 1:
        # prefix query
    elif "*" in value:
        # wildcard query
    else:
        # match query (full-text)
```

### Step 3: Compile Boolean Tree
- Split by OR into groups
- Each group is a conjunction (AND) of its terms
- Negated terms collected separately into `must_not`
- Final structure:

```json
{
  "query": {
    "conjuncts": [
      { "disjuncts": [ /* OR groups */ ] },
      { "must_not": { "disjuncts": [ /* negated terms */ ] } }
    ]
  }
}
```

---

## FTS Index Fields Reference

| Field | Type | Notes |
|---|---|---|
| `rawLog` | text | Main log line content, standard analyzer |
| `type` | text | Log type (e.g., `Sync:Active`), stored + docvalues |
| `mainType` | text | Top-level type (e.g., `Sync`), stored + docvalues |
| `processId` | number | Numeric only — no wildcard/match support |
| `error` | boolean | true/false |
| `dt` | datetime | ISO timestamp |
| `dtEpoch` | number | Unix epoch for sorting/range |

---

## Risks & Notes

- **Phrase queries may need index changes** — verify term vector support on text fields before enabling `match_phrase`
- **Substring matching is not supported** — FTS is token-based, not grep-like. Document this clearly in the UI help tooltip.
- **Leading wildcards (`*foo`) can be slow** — consider rejecting for now
- **Only-negative queries** (e.g., just `-healthcheck`) need a positive base — combine with date/type filters or reject with a message
- **Future:** If users need raw substring search, add an ngram analyzer field to the index

---

## Updated Help Tooltip Text

```
Search logs with terms, phrases, and filters.

Examples:
  push error              → both terms required (AND)
  push OR error           → either term
  -healthcheck            → exclude term
  "connection refused"    → exact phrase
  type:Sync               → field filter
  pid:1047                → by process ID
  error:true              → errors only
  retry*                  → prefix match
```
