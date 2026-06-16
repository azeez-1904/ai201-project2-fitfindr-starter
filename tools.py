"""
tools.py

The three required FitFindr tools. Each tool is a standalone function that
can be called and tested independently before being wired into the agent loop.

Complete and test each tool before moving to agent.py.

Tools:
    search_listings(description, size, max_price)  → list[dict]
    suggest_outfit(new_item, wardrobe)              → str
    create_fit_card(outfit, new_item)               → str
"""

import os
import re

from dotenv import load_dotenv
from groq import Groq

from utils.data_loader import load_listings

load_dotenv()

# The fixed LLM stack for this project.
GROQ_MODEL = "llama-3.3-70b-versatile"

# Short, low-signal tokens we drop before keyword scoring in search_listings.
_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from",
    "how", "i", "im", "in", "is", "it", "its", "looking", "me", "my", "of",
    "on", "or", "out", "size", "some", "something", "style", "that", "the",
    "there", "to", "under", "want", "wear", "what", "whats", "with", "would",
    "you", "your",
}


# ── Groq client ───────────────────────────────────────────────────────────────

def _get_groq_client():
    """Initialize and return a Groq client using GROQ_API_KEY from .env."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError(
            "GROQ_API_KEY not set. Add it to a .env file in the project root."
        )
    return Groq(api_key=api_key)


def _tokenize(text: str) -> list[str]:
    """Lowercase a string and split into meaningful word tokens (stopwords dropped)."""
    words = re.findall(r"[a-z0-9]+", text.lower())
    return [w for w in words if w not in _STOPWORDS and len(w) > 1]


# ── Tool 1: search_listings ───────────────────────────────────────────────────

def search_listings(
    description: str,
    size: str | None = None,
    max_price: float | None = None,
) -> list[dict]:
    """
    Search the mock listings dataset for items matching the description,
    optional size, and optional price ceiling.

    Args:
        description: Keywords describing what the user is looking for
                     (e.g., "vintage graphic tee").
        size:        Size string to filter by, or None to skip size filtering.
                     Matching is case-insensitive (e.g., "M" matches "S/M").
        max_price:   Maximum price (inclusive), or None to skip price filtering.

    Returns:
        A list of matching listing dicts, sorted by relevance (best match first).
        Returns an empty list if nothing matches — does NOT raise an exception.

    Each listing dict has the following fields:
        id, title, description, category, style_tags (list), size,
        condition, price (float), colors (list), brand, platform

    TODO:
        1. Load all listings with load_listings().
        2. Filter by max_price and size (if provided).
        3. Score each remaining listing by keyword overlap with `description`.
        4. Drop any listings with a score of 0 (no relevant matches).
        5. Sort by score, highest first, and return the listing dicts.

    Before writing code, fill in the Tool 1 section of planning.md.
    """
    listings = load_listings()
    query_tokens = _tokenize(description)

    size_filter = size.strip().lower() if size and size.strip() else None

    scored: list[tuple[int, float, dict]] = []
    for item in listings:
        # 1. Price filter (inclusive ceiling).
        if max_price is not None and item["price"] > max_price:
            continue

        # 2. Size filter: case-insensitive substring match (e.g. "M" in "S/M").
        if size_filter is not None and size_filter not in item["size"].lower():
            continue

        # 3. Relevance score by keyword overlap. Title and style_tags are the
        #    strongest signals, so a token found there is weighted higher than
        #    one found only in the longer description / category / colors / brand.
        strong = " ".join([item["title"], " ".join(item["style_tags"])]).lower()
        weak = " ".join(
            [item["description"], item["category"], " ".join(item["colors"]),
             item["brand"] or ""]
        ).lower()

        score = 0
        for token in query_tokens:
            if token in strong:
                score += 2
            elif token in weak:
                score += 1

        # 4. Drop listings with no keyword relevance at all.
        if score > 0:
            scored.append((score, item["price"], item))

    # 5. Sort by score (desc); break ties by lower price first.
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [item for _, _, item in scored]


# ── Tool 2: suggest_outfit ────────────────────────────────────────────────────

def suggest_outfit(new_item: dict, wardrobe: dict) -> str:
    """
    Given a thrifted item and the user's wardrobe, suggest 1–2 complete outfits.

    Args:
        new_item: A listing dict (the item the user is considering buying).
        wardrobe: A wardrobe dict with an 'items' key containing a list of
                  wardrobe item dicts. May be empty — handle this gracefully.

    Returns:
        A non-empty string with outfit suggestions.
        If the wardrobe is empty, offer general styling advice for the item
        rather than raising an exception or returning an empty string.

    TODO:
        1. Check whether wardrobe['items'] is empty.
        2. If empty: call the LLM with a prompt for general styling ideas
           (what kinds of items pair well, what vibe it suits, etc.).
        3. If not empty: format the wardrobe items into a prompt and ask
           the LLM to suggest specific outfit combinations using the new item
           and named pieces from the wardrobe.
        4. Return the LLM's response as a string.

    Before writing code, fill in the Tool 2 section of planning.md.
    """
    item_desc = (
        f"{new_item.get('title', 'this piece')} "
        f"(category: {new_item.get('category', 'unknown')}; "
        f"style: {', '.join(new_item.get('style_tags', [])) or 'n/a'}; "
        f"colors: {', '.join(new_item.get('colors', [])) or 'n/a'})"
    )

    items = wardrobe.get("items", [])
    if not items:
        # Empty / new-user wardrobe: general styling advice, no owned pieces.
        prompt = (
            "You are a thoughtful personal stylist. A shopper is considering "
            f"this secondhand piece: {item_desc}.\n\n"
            "They have not entered any wardrobe items yet, so do not reference "
            "specific pieces they own. Give general styling advice in 3-5 "
            "sentences: what kinds of items pair well with it, what colors and "
            "silhouettes work, and what overall vibe or occasion it suits."
        )
    else:
        # Populated wardrobe: combine the new item with named owned pieces.
        wardrobe_lines = "\n".join(
            f"- {it['name']} (category: {it['category']}; "
            f"colors: {', '.join(it.get('colors', []))}; "
            f"style: {', '.join(it.get('style_tags', []))})"
            for it in items
        )
        prompt = (
            "You are a thoughtful personal stylist. A shopper is considering "
            f"this secondhand piece: {item_desc}.\n\n"
            "Here is their existing wardrobe:\n"
            f"{wardrobe_lines}\n\n"
            "Suggest 1-2 complete outfits that combine the new piece with "
            "specific items named above. Refer to the owned pieces by name. "
            "Keep it to a short, friendly paragraph or two and explain why the "
            "combination works."
        )

    try:
        client = _get_groq_client()
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=400,
        )
        return response.choices[0].message.content.strip()
    except Exception as exc:  # network, auth, rate limit, etc.
        return (
            "Could not generate an outfit right now. Please check your "
            f"connection or API key and try again. ({type(exc).__name__})"
        )


# ── Tool 3: create_fit_card ───────────────────────────────────────────────────

def create_fit_card(outfit: str, new_item: dict) -> str:
    """
    Generate a short, shareable outfit caption for the thrifted find.

    Args:
        outfit:   The outfit suggestion string from suggest_outfit().
        new_item: The listing dict for the thrifted item.

    Returns:
        A 2–4 sentence string usable as an Instagram/TikTok caption.
        If outfit is empty or missing, return a descriptive error message
        string — do NOT raise an exception.

    The caption should:
    - Feel casual and authentic (like a real OOTD post, not a product description)
    - Mention the item name, price, and platform naturally (once each)
    - Capture the outfit vibe in specific terms
    - Sound different each time for different inputs (use higher LLM temperature)

    TODO:
        1. Guard against an empty or whitespace-only outfit string.
        2. Build a prompt that gives the LLM the item details and the outfit,
           and asks for a caption matching the style guidelines above.
        3. Call the LLM and return the response.

    Before writing code, fill in the Tool 3 section of planning.md.
    """
    # 1. Guard against a missing / empty / whitespace-only outfit.
    if not outfit or not outfit.strip():
        return (
            "No outfit was provided, so a fit card cannot be written. "
            "Generate an outfit first."
        )

    title = new_item.get("title", "this thrifted find")
    price = new_item.get("price")
    price_str = f"${price:.0f}" if isinstance(price, (int, float)) else "a steal"
    platform = new_item.get("platform", "secondhand")

    prompt = (
        "Write a short, shareable social media caption (2-4 sentences) for an "
        "outfit-of-the-day post about a thrifted find. Make it sound casual and "
        "authentic, like a real OOTD post, not a product description.\n\n"
        f"Item: {title}\n"
        f"Price: {price_str}\n"
        f"Found on: {platform}\n"
        f"Outfit: {outfit}\n\n"
        f"Mention the item name, the price ({price_str}), and the platform "
        f"({platform}) naturally, once each. Capture the outfit's vibe in "
        "specific terms. Do not use hashtags unless they feel natural."
    )

    try:
        client = _get_groq_client()
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.95,  # high, so repeated calls vary
            max_tokens=200,
        )
        return response.choices[0].message.content.strip()
    except Exception as exc:
        return (
            "Could not write a fit card right now. Please try again. "
            f"({type(exc).__name__})"
        )
