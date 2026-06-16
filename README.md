# FitFindr

FitFindr is a multi-tool AI agent that helps a shopper find secondhand clothing and figure out how to wear it. You describe what you want in plain language (optionally with a size and a price ceiling), and the agent finds the best matching listing, suggests how to style it with clothes you already own, and writes a short shareable caption for the find.

It is built on three tools orchestrated by a deterministic planning loop, with state carried between tools in a single session dict. The two generative tools call Groq's `llama-3.3-70b-versatile`; the search tool is pure Python.

## Setup

```bash
pip install -r requirements.txt
```

Create a `.env` file in this directory with your Groq key (free at console.groq.com). It is gitignored and must never be committed:

```
GROQ_API_KEY=your_key_here
```

Run the app:

```bash
python app.py
```

Then open the localhost URL shown in the terminal (usually http://localhost:7860).

Run the tests:

```bash
pytest tests/
```

## Tool Inventory

| Tool | Inputs | Output | Purpose |
|------|--------|--------|---------|
| `search_listings` | `description: str`, `size: str \| None`, `max_price: float \| None` | `list[dict]` of full listing dicts, ranked best match first; `[]` when nothing matches | Filter the 40 mock listings by price and size, then score and rank by keyword relevance. Pure Python, no LLM. |
| `suggest_outfit` | `new_item: dict` (a listing), `wardrobe: dict` (has an `items` list) | `str` of outfit prose | Use Groq to combine the found item with named wardrobe pieces, or give general advice when the wardrobe is empty. |
| `create_fit_card` | `outfit: str`, `new_item: dict` | `str`, a 2 to 4 sentence caption | Use Groq (high temperature) to write a casual, shareable OOTD caption that names the item, price, and platform once each. |

Field detail:

- A **listing dict** has: `id`, `title`, `description`, `category`, `style_tags` (list), `size`, `condition`, `price` (float), `colors` (list), `brand` (str or None), `platform`.
- A **wardrobe item dict** has: `id`, `name`, `category`, `colors` (list), `style_tags` (list), `notes` (str or None).

## How the Planning Loop Works (Conditional Logic)

`run_agent(query, wardrobe)` runs a fixed three-tool pipeline with one decision point. It does not call all three tools unconditionally.

1. Initialize a fresh session with `_new_session()`.
2. Parse the query into `description`, `size`, and `max_price` using regex (no LLM). A price cue like "under $30" sets `max_price`; an explicit "size M" phrase sets `size`; the remainder becomes the `description`.
3. Call `search_listings(description, size, max_price)`.
   - **If results are empty:** set `session["error"]` to a specific message (what was searched plus what to try), leave `selected_item`, `outfit_suggestion`, and `fit_card` as `None`, and return immediately. The two LLM tools are never called.
   - **If results are non-empty:** set `session["selected_item"]` to the top-ranked result and continue.
4. Call `suggest_outfit(selected_item, wardrobe)` and store the result.
5. Call `create_fit_card(outfit_suggestion, selected_item)` and store the result.
6. Return the session.

The only branch is the emptiness of the search results. Everything downstream needs a selected item, so an empty search is the single condition that changes control flow.

## State Management

All state for one interaction lives in a single `session` dict built by `_new_session()`. Tools never call each other and never share globals; the loop writes each tool's output into a named key, and the next tool reads from that key. The exact object stored in `session["selected_item"]` is the same dict passed to both `suggest_outfit` and `create_fit_card`, and the exact string in `session["outfit_suggestion"]` is the same string passed to `create_fit_card`. No information is re-entered or recomputed.

| Key | Written by | Read by |
|-----|-----------|---------|
| `query` | `_new_session` | parse step |
| `parsed` | parse step | `search_listings` call |
| `search_results` | after search | branch check |
| `selected_item` | after non-empty search | `suggest_outfit`, `create_fit_card` |
| `wardrobe` | `_new_session` | `suggest_outfit` |
| `outfit_suggestion` | after `suggest_outfit` | `create_fit_card` |
| `fit_card` | after `create_fit_card` | UI / caller |
| `error` | on early exit | UI / caller |

The caller (`handle_query` in `app.py`) checks `session["error"]` first. If it is `None`, it formats `selected_item` into the listing panel and returns `outfit_suggestion` and `fit_card` for the other two panels.

## Error Handling (per tool, with examples)

**`search_listings`, no results.** Returns `[]`, never raises. The loop turns that into a helpful message. Verified:

```
$ search_listings('designer ballgown spacesuit', 'XXS', 5)  ->  []
$ run_agent('designer ballgown size XXS under $5', example_wardrobe)
  session['error'] = "No matches for 'designer ballgown' in size XXS under $5.
  Try raising your price, removing the size filter, or using broader terms
  (for example 'tee' or 'jacket')."
  outfit_suggestion is None: True | fit_card is None: True
```

**`suggest_outfit`, empty wardrobe.** Not treated as a failure. It detects `wardrobe["items"] == []` and switches to a general-advice prompt instead of crashing. Verified: calling it with `get_empty_wardrobe()` returned several sentences of general styling guidance with no references to owned pieces. It also wraps the Groq call in a try/except and returns a plain error string if the API fails.

**`create_fit_card`, missing outfit.** Guards `None`, empty, and whitespace-only input. Verified:

```
$ create_fit_card('', item)
  -> "No outfit was provided, so a fit card cannot be written.
      Generate an outfit first."
```

It also catches Groq API exceptions and returns a short error string rather than raising.

**`handle_query`, empty query.** Guards an empty or whitespace query before calling the agent and returns "Please describe what you're looking for." in the listing panel.

## Spec Reflection

**One way the spec helped.** Writing the Tool and State Management sections of `planning.md` before any code meant the session dict had a defined contract (which key each tool writes and reads) before `run_agent` existed. Implementing the loop became almost mechanical: each step mapped to one key write, and the single decision point (empty search results) was already identified, so the early-return branch was obvious rather than discovered mid-coding.

**One way the implementation diverged.** The step-by-step trace in `planning.md` predicted that the query "vintage graphic tee under $30" would surface listing `lst_006` (Graphic Tee, $24) as the top result. In practice the agent surfaced `lst_002` (Y2K Baby Tee, $18). Both score equally on the keywords "vintage", "graphic", and "tee", and the tie-break rule I specified (lower price first) correctly favored the $18 tee over the $24 one. The divergence was the spec's prediction being imprecise about ties, not a bug; the behavior matches the documented rule, so I kept it and noted the tie-break explicitly.

## AI Usage

**Instance 1: implementing `search_listings` from the Tool 1 spec.** I directed Claude Code to implement the scorer using `load_listings()`, filtering by price and size and ranking by keyword overlap. I revised the first cut so that matches in the `title` and `style_tags` count for more than matches buried in the long `description`, and I added a stopword list so filler words like "looking", "wear", and "under" do not inflate scores. I also added a tie-break by lower price so equal-relevance results have a stable, sensible order.

**Instance 2: API key handling.** The cloned starter did not include a `.env`, so I directed the AI to source my existing Groq key from a sibling project rather than hardcode anything. I revised the approach to write the key only into a gitignored `.env` (confirmed with `git check-ignore`) and to load it through `python-dotenv`, keeping the secret out of source control while letting the two LLM tools run locally.
