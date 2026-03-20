# Dynamic Focused Prompt Assembly

## Problem

The agent receives all 12 recipe workflows (~2500 tokens) in every system prompt, regardless of task type. It uses one and ignores eleven. This context noise competes for attention, causing the LLM to miss critical field requirements — particularly on complex recipes like voucher postings where `row`, `description`, and posting structure are buried among unrelated recipes.

Production evidence (6 submissions, 2026-03-20):
- Supplier invoice: agent omitted `row` on voucher postings 5 times in a row, hit max iterations
- Voucher with dimensions: agent omitted `description` and `row` on first attempt, recovered after 2 errors
- All other tasks (departments, customers, invoices): 0 errors — simpler recipes with less competition for attention

## Solution

Use the pre-parser's recipe letter to dynamically assemble a focused system prompt containing only the relevant recipe and its OpenAPI schemas. The agent sees exactly what it needs — nothing more.

## Architecture

```
User prompt
    |
    v
Pre-parser (unchanged)
    | outputs: recipe letter + extracted fields
    v
Prompt assembler (new)
    | inputs: recipe letter
    | looks up: RECIPES[letter] + get_recipe_schemas(letter)
    | builds: core rules + single recipe + compact schema
    v
Agent (receives focused ~800-1100 token context)
```

### Before (current)

```
System prompt (~3500 tokens):
  - 9 rules
  - 12 recipes (A through L)
  - Action instruction

User message:
  - Pre-parsed plan (recipe letter + fields)
  - Compact schema for matched recipe (~200-500 tokens)
  - Original prompt
```

### After (proposed)

```
System prompt (~800-1100 tokens):
  - 9 universal rules
  - 1 recipe (the matched one only)
  - Compact schema (moved from user message into system prompt)
  - Action instruction

User message:
  - Pre-parsed plan (recipe letter + fields)
  - Original prompt
```

## Design Decisions

### Pre-parser stays lightweight
The pre-parser identifies the recipe letter and extracts field values. It does NOT generate API call sequences or field mappings. This keeps it cheap (one LLM call, no tools) and limits blast radius if it makes mistakes.

### Trust the pre-parser
If the pre-parser says Recipe I, the agent only sees Recipe I. No neighbor recipes, no fallback recipe list. If misclassification happens, we fix the pre-parser prompt — not add complexity to the agent. The original prompt is still passed for reference, and `search_api_docs` remains available as an escape hatch.

### Rules stay universal
All 9 rules apply to every task type. Endpoint-specific gotchas (like `row` starts at 1, `amountGross` not `amount`) live inside the recipe text, not in the rules. The agent sees the gotcha right next to the endpoint it applies to.

### Schema moves into system prompt
Currently compact schemas are injected into the user message. Moving them into the system prompt alongside the recipe keeps all instructions in one place. The user message becomes just: pre-parsed plan + original prompt.

### Fallback: full prompt if pre-parse fails
If `_pre_parse()` returns None (LLM error, timeout), fall back to the current behavior: full system prompt with all 12 recipes. This is the existing graceful degradation path.

## Changes

### 1. Split `_SYSTEM_PROMPT` into components

```python
_CORE_RULES = """You are a Tripletex API agent. Complete accounting tasks via API calls.
The task has been pre-parsed into English with extracted fields — trust the parsed plan.

## Rules
1. API success IS confirmation. NEVER GET after POST/PUT/DELETE.
2. Include EVERY value from the task prompt. Every field is scored.
   Check the API fields below for correct field names.
3. Follow the recipe below. Do not add verification steps.
4. On error, read the error message and fix in ONE retry.
   Only search docs if the error suggests wrong endpoint entirely.
5. GET returns {values:[...]}, POST/PUT returns {value:{...}}. Reuse returned IDs.
6. When no date is specified, use today's date ({today}). Never invent future dates.
   Dates: YYYY-MM-DD. For vouchers, use fiscal year 2026. Addresses: object, not string.
7. GET paymentType/vatType/costCategory ONCE with no filters. Pick from full response.
8. If the task says to create/register/add/update/delete, you MUST make a mutation call.
9. Preserve Norwegian characters exactly as given.
"""

_RECIPES = {
    'A': """## Recipe: DEPARTMENT
... (single recipe text) ...""",
    'B': """## Recipe: EMPLOYEE
... """,
    # ... one entry per letter A-L
}

_ACTION = """## Action
You MUST use call_api to complete the task. Start immediately.
Never respond with only text. On 403 auth errors, retry.
NEVER give up or say you cannot complete the task."""

# Full prompt for fallback (all recipes concatenated)
_FULL_RECIPES = "## Recipes\n\n" + "\n\n".join(_RECIPES.values())
```

### 2. Make `get_system_prompt()` dynamic

```python
def get_system_prompt(recipe_letter: str | None = None) -> str:
    today = date.today().isoformat()
    rules = _CORE_RULES.format(today=today)

    if recipe_letter and recipe_letter in _RECIPES:
        recipe = _RECIPES[recipe_letter]
        schema = get_recipe_schemas(f"RECIPE: {recipe_letter}")
        parts = [rules, recipe]
        if schema:
            parts.append(schema)
        parts.append(_ACTION)
        return "\n\n".join(parts)

    # Fallback: all recipes (pre-parse failed or unknown letter)
    return "\n\n".join([rules, _FULL_RECIPES, _ACTION])
```

### 3. Extract recipe letter in `solve()`

```python
def solve(self, prompt: str) -> None:
    # ... existing setup ...

    parsed_plan = self._pre_parse(prompt)

    # Extract recipe letter for dynamic prompt assembly
    recipe_letter = None
    if parsed_plan:
        import re
        match = re.search(r'RECIPE:\s*([A-L])', parsed_plan)
        if match:
            recipe_letter = match.group(1)

    # Build focused system prompt
    system_prompt = get_system_prompt(recipe_letter)

    if parsed_plan:
        # Schema is now in the system prompt — don't inject it here again
        user_message = f"Pre-parsed task plan:\n{parsed_plan}\n\nOriginal prompt:\n{prompt}"
    else:
        user_message = f"Task: {prompt}"
        # ... existing file_contents fallback ...

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]
    # ... rest of agent loop unchanged ...
```

Note: remove the existing `schema_block = get_recipe_schemas(parsed_plan)` code from `solve()` — schema injection is now handled inside `get_system_prompt()`.

### 4. No changes needed

- **Pre-parser** (`_PRE_PARSE_PROMPT`): unchanged
- **Tool definitions** (`CALL_API_TOOL`, `SEARCH_API_DOCS_TOOL`): unchanged
- **422 error schema hints** (`get_endpoint_schema`): unchanged
- **`search_api_docs`**: unchanged, still available as escape hatch
- **`mock_client.py`**: unchanged
- **Recipe content**: the text of each recipe stays the same, just stored per-letter instead of in one big string

## Token Budget

| Component | Current | Proposed |
|-----------|---------|----------|
| Core rules | ~400 | ~400 |
| Recipes | ~2500 (all 12) | ~100-500 (1 recipe; Recipe I is longest at ~500) |
| Compact schema | ~200-500 (in user msg) | ~200-500 (in system prompt) |
| Action instruction | ~60 | ~60 |
| **System prompt total** | **~3000** | **~800-1400** |
| User message (plan + prompt) | ~500-1000 | ~500-1000 (no schema) |

Net savings: ~1600-2200 tokens per request. More importantly, the signal-to-noise ratio improves dramatically — the agent reads 1 recipe, not 12.

## Testing

- **Unit tests**: `get_system_prompt('I')` returns only Recipe I text, contains `row`, contains compact schema
- **Unit tests**: `get_system_prompt('I')` does NOT contain Recipe A, B, C etc.
- **Unit tests**: `get_system_prompt(None)` returns full prompt with all recipes (fallback)
- **Unit tests**: `get_system_prompt('Z')` returns full prompt (unknown letter)
- **Regression test**: `assert "row" in get_system_prompt('I')` — the exact failure that motivated this design
- **Unit tests**: each letter A-L produces a valid focused prompt
- **Existing tuning tests**: should pass or improve (agent gets less noise)
- **New tuning test**: supplier invoice scenario that previously hit max iterations

## Risks

| Risk | Mitigation |
|------|------------|
| Pre-parser misclassifies task | Original prompt passed as reference; `search_api_docs` available; fix pre-parser prompt. Recipe letter logged in agent summary for easy debugging. |
| Recipe text doesn't cover edge case | Agent can still search docs (2 searches allowed) |
| Splitting recipes introduces copy errors | Unit test validates each recipe letter produces valid prompt |
| Curly braces in recipe text break `.format()` | All literal `{` `}` in recipe strings must be doubled `{{` `}}` since `_CORE_RULES` uses `.format(today=today)`. Note: only `_CORE_RULES` is formatted; `_RECIPES` values are NOT formatted, so they can use single braces safely. |

## Implementation Notes

- Recipe I includes all three sub-sections (basic voucher, dimensions, supplier invoice) as a single `_RECIPES['I']` entry
- Only `_CORE_RULES` uses `.format(today=today)` — recipe strings are concatenated raw, so curly braces in JSON examples don't need escaping
- Log the detected `recipe_letter` in the agent summary line for production debugging
- `generate_endpoint_reference()` in api_docs.py is unused in production — leave as-is, not related to this change

## Files to modify

- `src/agent.py` — split prompt into `_CORE_RULES` + `_RECIPES` dict + `_ACTION`, dynamic `get_system_prompt(letter)`, remove schema injection from `solve()`, log recipe letter in summary
- `src/api_docs.py` — no changes (compact schema already works)
- `tests/test_agent.py` — update system prompt tests for dynamic behavior, add focused path tests
- `tests/test_prompt_validation.py` — add tests for per-recipe prompt assembly
