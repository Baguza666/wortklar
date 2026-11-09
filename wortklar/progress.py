"""
Wortklar A1 Curriculum Tracker & Progress Engine.
Manages Goethe / telc A1 core vocabulary, smart difficulty categorization,
lookup frequency tracking, and user mastery persistence.
"""

import json
import os
import threading
import time
from typing import Dict, Any, List, Optional

DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "goethe_a1.json")
PROGRESS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "user_progress.json")

_cache_lock = threading.Lock()
_goethe_words: Optional[List[Dict[str, Any]]] = None
_goethe_lookup_index: Optional[Dict[str, Dict[str, Any]]] = None


def load_goethe_words() -> List[Dict[str, Any]]:
    """Load canonical Goethe A1 vocabulary list."""
    global _goethe_words, _goethe_lookup_index
    with _cache_lock:
        if _goethe_words is not None:
            return _goethe_words

        if not os.path.exists(DATA_PATH):
            _goethe_words = []
            _goethe_lookup_index = {}
            return _goethe_words

        try:
            with open(DATA_PATH, "r", encoding="utf-8") as f:
                _goethe_words = json.load(f)
        except Exception:
            _goethe_words = []

        _goethe_lookup_index = {}
        for item in _goethe_words:
            hw_lower = item["headword"].lower()
            _goethe_lookup_index[hw_lower] = item

        return _goethe_words


def get_goethe_word_info(word: str) -> Optional[Dict[str, Any]]:
    """Check if a word is in the Goethe A1 curriculum."""
    load_goethe_words()
    if not word or not _goethe_lookup_index:
        return None
    return _goethe_lookup_index.get(word.strip().lower())


def load_user_progress() -> Dict[str, Dict[str, Any]]:
    """Load user progress from storage."""
    if not os.path.exists(PROGRESS_FILE):
        return {}
    try:
        with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_user_progress(progress_data: Dict[str, Dict[str, Any]]) -> None:
    """Save user progress to storage."""
    try:
        tmp_file = PROGRESS_FILE + ".tmp"
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(progress_data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_file, PROGRESS_FILE)
    except Exception as ex:
        pass


def record_word_interaction(
    word: str,
    action: str = "lookup",
    new_status: Optional[str] = None
) -> Dict[str, Any]:
    """
    Record an interaction with a word:
    - action='lookup': increments lookup_count, sets status to 'learning' if unseen.
    - action='master': sets status to 'mastered'.
    - action='learn': sets status to 'learning'.
    - action='reset': sets status to 'unseen' and lookup_count to 0.

    Smart difficulty logic:
    - If lookup_count >= 3: tagged 'hard' (user repeatedly searches it).
    - If lookup_count == 2: tagged 'medium'.
    - If lookup_count <= 1 and mastered: tagged 'easy'.
    """
    clean_w = word.strip().lower()
    goethe_info = get_goethe_word_info(clean_w)

    progress = load_user_progress()
    entry = progress.get(clean_w, {
        "status": "unseen",
        "lookup_count": 0,
        "difficulty": goethe_info.get("base_difficulty", "easy") if goethe_info else "easy",
        "last_interaction": int(time.time())
    })

    if action == "lookup":
        entry["lookup_count"] = entry.get("lookup_count", 0) + 1
        if entry["status"] == "unseen":
            entry["status"] = "learning"
    elif action == "master":
        entry["status"] = "mastered"
    elif action == "learn":
        entry["status"] = "learning"
    elif action == "reset":
        entry["status"] = "unseen"
        entry["lookup_count"] = 0

    if new_status in ("unseen", "learning", "mastered"):
        entry["status"] = new_status

    # Smart Difficulty Categorization
    l_count = entry.get("lookup_count", 0)
    if l_count >= 3:
        entry["difficulty"] = "hard"
    elif l_count >= 2:
        entry["difficulty"] = "medium"
    elif entry["status"] == "mastered" and l_count <= 1:
        entry["difficulty"] = "easy"
    elif goethe_info:
        entry["difficulty"] = goethe_info.get("base_difficulty", "easy")

    entry["last_interaction"] = int(time.time())
    progress[clean_w] = entry
    save_user_progress(progress)

    return entry


def get_a1_hub_data(category_filter: Optional[str] = None, difficulty_filter: Optional[str] = None) -> Dict[str, Any]:
    """
    Get full A1 Curriculum Hub data with progress, stats, and filtered wordlist.
    """
    words = load_goethe_words()
    progress = load_user_progress()

    items = []
    stats = {
        "total": len(words),
        "mastered": 0,
        "learning": 0,
        "unseen": 0,
        "percentage": 0.0,
        "categories": {},
        "difficulties": {"easy": 0, "medium": 0, "hard": 0}
    }

    category_names = {
        "conversation": "Greetings & Basics",
        "family": "Family & People",
        "food": "Food & Drink",
        "housing": "Housing & Home",
        "travel": "Travel & Directions",
        "work": "Work & Study",
        "health": "Health & Body",
        "shopping": "Shopping & Money",
        "time": "Time & Calendar",
        "weather": "Weather & Nature"
    }

    for cat_key, cat_name in category_names.items():
        stats["categories"][cat_key] = {
            "name": cat_name,
            "total": 0,
            "mastered": 0
        }

    for w in words:
        hw_lower = w["headword"].lower()
        user_p = progress.get(hw_lower, {})
        status = user_p.get("status", "unseen")
        lookup_count = user_p.get("lookup_count", 0)

        # Smart difficulty
        if lookup_count >= 3:
            diff = "hard"
        elif lookup_count >= 2:
            diff = "medium"
        elif status == "mastered" and lookup_count <= 1:
            diff = "easy"
        else:
            diff = w.get("base_difficulty", "easy")

        cat = w.get("category", "conversation")

        # Update stats
        if status == "mastered":
            stats["mastered"] += 1
            if cat in stats["categories"]:
                stats["categories"][cat]["mastered"] += 1
        elif status == "learning":
            stats["learning"] += 1
        else:
            stats["unseen"] += 1

        if cat in stats["categories"]:
            stats["categories"][cat]["total"] += 1

        if diff in stats["difficulties"]:
            stats["difficulties"][diff] += 1

        # Apply filters
        if category_filter and category_filter != "all" and cat != category_filter:
            continue
        if difficulty_filter and difficulty_filter != "all" and diff != difficulty_filter:
            continue

        items.append({
            "headword": w["headword"],
            "article": w.get("article"),
            "part_of_speech": w.get("part_of_speech"),
            "category": cat,
            "category_name": category_names.get(cat, cat),
            "english": w.get("english"),
            "example_de": w.get("example_de"),
            "example_en": w.get("example_en"),
            "status": status,
            "lookup_count": lookup_count,
            "difficulty": diff
        })

    if stats["total"] > 0:
        stats["percentage"] = round((stats["mastered"] / stats["total"]) * 100, 1)

    return {
        "stats": stats,
        "words": items,
        "categories": category_names
    }
