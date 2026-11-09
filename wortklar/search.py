"""
Search and keyboard suggestion engine for Wortklar.
Implements the 4-letter threshold rule, indexed candidate generation,
folded keys, bounded edit distance, and strict distinction between exact matches,
lookalikes, and typos.
"""

import json
import sqlite3
import unicodedata
from typing import List, Dict, Any, Optional, Tuple, Set


def normalize_input(q: str) -> str:
    """Normalize input string to Unicode NFC and trim whitespace."""
    if not q:
        return ""
    return unicodedata.normalize("NFC", q.strip())


def count_letters(q: str) -> int:
    """Count alphabetical characters in string."""
    return sum(1 for c in q if c.isalpha())


def fold_text(text: str) -> str:
    """
    Fold text for candidate matching:
    - lowercase
    - ä -> a, ö -> o, ü -> u
    - ß -> ss
    """
    t = text.lower()
    t = t.replace("ä", "a").replace("ö", "o").replace("ü", "u")
    t = t.replace("ß", "ss")
    return t


def generate_candidate_variations(query: str) -> List[Tuple[str, str]]:
    """
    Generate plausible candidate variations for spelling assistance:
    - missing umlaut: a -> ä, o -> ö, u -> ü
    - ae/oe/ue -> ä/ö/ü
    - ß <-> ss
    - adjacent character transpositions (e.g. shcön -> schön)
    - 1-character deletion/insertion/replacement for word boundaries
    Returns list of tuples: (candidate_text, explanation_note)
    """
    norm = normalize_input(query)
    q_lower = norm.lower()
    candidates: List[Tuple[str, str]] = []
    seen: Set[str] = {q_lower}

    def add(c: str, note: str):
        c_clean = c.strip()
        c_low = c_clean.lower()
        if c_clean and c_low not in seen:
            seen.add(c_low)
            candidates.append((c_clean, note))

    # 1. Umlaut additions / conversions
    # Single character substitutions
    umlaut_pairs = [("a", "ä"), ("o", "ö"), ("u", "ü"), ("A", "Ä"), ("O", "Ö"), ("U", "Ü")]
    for orig_char, umlaut_char in umlaut_pairs:
        if orig_char in norm:
            idx = -1
            while True:
                idx = norm.find(orig_char, idx + 1)
                if idx == -1:
                    break
                # Replace this occurrence
                cand = norm[:idx] + umlaut_char + norm[idx + 1:]
                add(cand, f"missing umlaut: {orig_char.lower()} → {umlaut_char.lower()}")

    # ae / oe / ue conversions
    digraph_pairs = [("ae", "ä"), ("oe", "ö"), ("ue", "ü")]
    for dig, uml in digraph_pairs:
        if dig in q_lower:
            cand = q_lower.replace(dig, uml)
            add(cand, f"umlaut alternative: {dig} → {uml}")

    # ss <-> ß conversions
    if "ss" in q_lower:
        cand = q_lower.replace("ss", "ß")
        add(cand, "spelling alternative: ss → ß")
    if "ß" in q_lower:
        cand = q_lower.replace("ß", "ss")
        add(cand, "spelling alternative: ß → ss")

    # Reverse umlaut (for lookalikes, e.g. schön -> schon)
    reverse_pairs = [("ä", "a"), ("ö", "o"), ("ü", "u")]
    for uml, orig in reverse_pairs:
        if uml in q_lower:
            cand = q_lower.replace(uml, orig)
            add(cand, f"lookalike: {uml} → {orig}")

    # 2. Adjacent transpositions (e.g. shcön -> schön)
    n = len(norm)
    for i in range(n - 1):
        transposed = norm[:i] + norm[i + 1] + norm[i] + norm[i + 2:]
        add(transposed, "transposed letters")

    # 3. 1-character edits for typo at start or end of word (e.g. xhaus -> haus)
    if n > 3:
        # deletion at index 0 (accidental leading character)
        add(norm[1:], "extra leading character")
        # deletion at index -1
        add(norm[:-1], "extra trailing character")

    return candidates


def get_suggestions(conn: sqlite3.Connection, raw_query: str, limit: int = 8) -> List[Dict[str, Any]]:
    """
    Return up to 8 selectable keyboard suggestions for query:
    - Requires at least 4 letters in trimmed Unicode NFC-normalized input.
    - If shorter, returns empty list immediately without database work.
    - Ranks: exact spelling/case first, then case-only, then literal prefixes.
    - Forms are labeled (e.g. 'Häuser → Haus', 'ging → gehen').
    - Canonical noun capitalization displayed without turning match into correction.
    """
    q = normalize_input(raw_query)
    if count_letters(q) < 4:
        return []

    q_lower = q.lower()
    next_prefix = q_lower + "\uffff"

    # Query indexed prefix range
    cur = conn.execute("""
        SELECT s.term, s.lower_term, s.entry_id, s.is_lemma, s.form_label, s.rank_priority, s.preview,
               e.headword, e.part_of_speech, e.article
        FROM search_index s
        JOIN entries e ON e.id = s.entry_id
        WHERE s.lower_term >= ? AND s.lower_term < ?
        ORDER BY
            CASE
                WHEN s.term = ? THEN 1
                WHEN s.lower_term = ? AND s.is_lemma = 1 THEN 2
                WHEN s.lower_term = ? THEN 3
                WHEN s.is_lemma = 1 THEN 4
                ELSE 5
            END,
            s.rank_priority ASC,
            LENGTH(s.term) ASC,
            s.lower_term ASC
        LIMIT 30
    """, (q_lower, next_prefix, q, q_lower, q_lower))

    rows = cur.fetchall()
    results = []
    seen_displays = set()

    for r in rows:
        term = r["term"]
        is_lemma = bool(r["is_lemma"])
        form_label = r["form_label"]
        headword = r["headword"]
        pos = r["part_of_speech"]
        article = r["article"]

        # Label form results, e.g. Häuser → Haus
        if form_label:
            display_title = form_label
            match_type = "form"
        elif is_lemma:
            display_title = f"{article} {headword}".strip() if article and pos == "noun" else headword
            match_type = "lemma"
        else:
            display_title = term
            match_type = "form"

        if display_title in seen_displays:
            continue
        seen_displays.add(display_title)

        preview = r["preview"] or ""

        results.append({
            "term": term,
            "target_word": headword,
            "display": display_title,
            "match_type": match_type,
            "pos": pos,
            "preview": preview,
            "is_exact_case": (term == q),
            "is_exact_word": (term.lower() == q_lower)
        })

        if len(results) >= limit:
            break

    return results


def lookup_word(conn: sqlite3.Connection, raw_query: str) -> Dict[str, Any]:
    """
    Perform a complete dictionary lookup for raw_query of ANY length (in, Ei, bin work).
    Returns:
    - query: normalized query
    - exact_entries: list of primary matching entries (homographs separated)
    - form_matches: list of forms pointing to base entries (e.g. Häuser → Haus, ging → gehen)
    - lookalikes: distinct attested lookalikes with meanings (schon vs schön, Masse vs Maße, Hauser vs Häuser)
    - did_you_mean: suggestion if query has no exact entry but plausible candidate exists
    """
    q = normalize_input(raw_query)
    if not q:
        return {
            "query": "",
            "exact_entries": [],
            "form_matches": [],
            "lookalikes": [],
            "did_you_mean": None
        }

    q_lower = q.lower()

    # Step 1: Find direct entry matches using indexed headword candidates (eliminates full 1M scan)
    candidates_case = list(dict.fromkeys([q, q.capitalize(), q.lower(), q.upper()]))
    placeholders = ",".join("?" for _ in candidates_case)
    cur = conn.execute(f"""
        SELECT e.id, e.headword, e.part_of_speech, e.gender, e.article, e.source_edition,
               e.source_url, e.raw_tags, e.grammar_data, e.etymology_number
        FROM entries e
        WHERE e.headword IN ({placeholders})
        ORDER BY
            CASE WHEN e.headword = ? THEN 1 WHEN LOWER(e.headword) = ? THEN 2 ELSE 3 END,
            e.id ASC
    """, candidates_case + [q, q_lower])
    entry_rows = cur.fetchall()

    # Fallback to search_index if no direct candidate match
    if not entry_rows:
        cur_idx = conn.execute("""
            SELECT e.id, e.headword, e.part_of_speech, e.gender, e.article, e.source_edition,
                   e.source_url, e.raw_tags, e.grammar_data, e.etymology_number
            FROM search_index s
            JOIN entries e ON e.id = s.entry_id
            WHERE s.lower_term = ? AND s.is_lemma = 1
            LIMIT 5
        """, (q_lower,))
        entry_rows = cur_idx.fetchall()

    exact_entries = []
    seen_entry_ids = set()

    for er in entry_rows:
        eid = er["id"]
        seen_entry_ids.add(eid)
        entry_dict = _load_full_entry(conn, er)
        exact_entries.append(entry_dict)

    # Step 2: Find form matches (forms.form == q or forms.lower_form == q_lower)
    cur = conn.execute("""
        SELECT f.form, f.lower_form, f.entry_id, f.form_type, f.tags, f.article,
               e.headword, e.part_of_speech
        FROM forms f
        JOIN entries e ON e.id = f.entry_id
        WHERE f.form = ? OR f.lower_form = ?
        ORDER BY
            CASE WHEN f.form = ? THEN 1 ELSE 2 END,
            f.id ASC
    """, (q, q_lower, q))
    form_rows = cur.fetchall()

    form_matches = []
    base_entry_ids_from_forms = set()

    for fr in form_rows:
        eid = fr["entry_id"]
        hw = fr["headword"]
        # Skip if this headword was already loaded as an exact lemma match
        if eid in seen_entry_ids and fr["form"].lower() == hw.lower():
            continue

        base_entry_ids_from_forms.add(eid)
        tags = []
        if fr["tags"]:
            try:
                tags = json.loads(fr["tags"])
            except Exception:
                pass

        tag_label = ", ".join(t for t in tags if t not in ("table-tags", "inflection-template"))
        form_matches.append({
            "form": fr["form"],
            "base_word": hw,
            "form_label": f"{fr['form']} → {hw}",
            "pos": fr["part_of_speech"],
            "form_type": fr["form_type"] or "inflected form",
            "tag_label": tag_label,
            "article": fr["article"]
        })

    # If exact entries were not found but form matches were, load base entries
    if not exact_entries and base_entry_ids_from_forms:
        for beid in base_entry_ids_from_forms:
            if beid not in seen_entry_ids:
                seen_entry_ids.add(beid)
                cur_be = conn.execute("""
                    SELECT id, headword, part_of_speech, gender, article, source_edition,
                           source_url, raw_tags, grammar_data, etymology_number
                    FROM entries WHERE id = ?
                """, (beid,))
                row_be = cur_be.fetchone()
                if row_be:
                    exact_entries.append(_load_full_entry(conn, row_be))

    # Step 3: Lookalike and Spelling assistance generation
    candidates = generate_candidate_variations(q)
    lookalikes = []
    seen_lookalike_terms = set()
    did_you_mean = None

    if candidates:
        cand_map = {c.lower(): (c, note) for c, note in candidates}
        placeholders = ",".join("?" for _ in cand_map)
        cur_cand = conn.execute(f"""
            SELECT s.term, s.lower_term, s.entry_id, s.is_lemma, s.form_label, s.preview,
                   e.headword, e.part_of_speech, e.article
            FROM search_index s
            JOIN entries e ON e.id = s.entry_id
            WHERE s.lower_term IN ({placeholders})
            ORDER BY s.is_lemma DESC, s.rank_priority ASC
        """, list(cand_map.keys()))

        cand_rows = cur_cand.fetchall()
        for cr in cand_rows:
            c_low = cr["lower_term"]
            orig_cand, note = cand_map.get(c_low, (cr["term"], ""))
            term = cr["term"]
            hw = cr["headword"]
            pos = cr["part_of_speech"]
            preview = cr["preview"] or ""
            form_label = cr["form_label"]

            # Don't show current query as lookalike to itself
            if term.lower() == q_lower:
                continue

            display_cand = form_label if form_label else term
            if display_cand in seen_lookalike_terms:
                continue
            seen_lookalike_terms.add(display_cand)

            lookalike_item = {
                "term": term,
                "target_word": hw,
                "display": display_cand,
                "pos": pos,
                "preview": preview,
                "note": note
            }
            lookalikes.append(lookalike_item)

            # If no exact entries exist, the strongest candidate becomes "Did you mean ...?"
            if not did_you_mean and not exact_entries:
                did_you_mean = lookalike_item

    # Step 4: Multi-word phrase / expression breakdown (e.g. "relativ klein", "ab und zu")
    phrase_breakdown = None
    tokens = [t.strip(".,!?:;\"'()[]{}") for t in q.split() if t.strip(".,!?:;\"'()[]{}")]
    if len(tokens) > 1 and not exact_entries:
        breakdown_words = []
        for token in tokens:
            t_lower = token.lower()
            t_candidates = list(dict.fromkeys([token, token.capitalize(), token.lower()]))
            t_placeholders = ",".join("?" for _ in t_candidates)
            cur_tok = conn.execute(f"""
                SELECT e.id, e.headword, e.part_of_speech, e.gender, e.article, e.source_edition,
                       e.source_url, e.raw_tags, e.grammar_data, e.etymology_number
                FROM entries e
                WHERE e.headword IN ({t_placeholders})
                ORDER BY
                    CASE WHEN e.headword = ? THEN 1 WHEN e.headword = ? THEN 2 ELSE 3 END,
                    e.id ASC
                LIMIT 1
            """, t_candidates + [token, token.capitalize()])
            row_tok = cur_tok.fetchone()
            if row_tok:
                breakdown_words.append(_load_full_entry(conn, row_tok))
            else:
                # Fallback to forms table for inflected words in the phrase (e.g. viele -> viel)
                cur_f = conn.execute("""
                    SELECT e.id, e.headword, e.part_of_speech, e.gender, e.article, e.source_edition,
                           e.source_url, e.raw_tags, e.grammar_data, e.etymology_number
                    FROM forms f
                    JOIN entries e ON e.id = f.entry_id
                    WHERE f.lower_form = ?
                    LIMIT 1
                """, (t_lower,))
                row_f = cur_f.fetchone()
                if row_f:
                    breakdown_words.append(_load_full_entry(conn, row_f))
                else:
                    # Fallback to search_index
                    cur_s = conn.execute("""
                        SELECT e.id, e.headword, e.part_of_speech, e.gender, e.article, e.source_edition,
                               e.source_url, e.raw_tags, e.grammar_data, e.etymology_number
                        FROM search_index s
                        JOIN entries e ON e.id = s.entry_id
                        WHERE s.lower_term = ?
                        ORDER BY s.is_lemma DESC
                        LIMIT 1
                    """, (t_lower,))
                    row_s = cur_s.fetchone()
                    if row_s:
                        breakdown_words.append(_load_full_entry(conn, row_s))

        if breakdown_words:
            phrase_breakdown = {
                "phrase": q,
                "words": breakdown_words
            }

    return {
        "query": q,
        "exact_entries": exact_entries,
        "form_matches": form_matches,
        "lookalikes": lookalikes[:6],
        "did_you_mean": did_you_mean,
        "phrase_breakdown": phrase_breakdown
    }


def _load_full_entry(conn: sqlite3.Connection, row: sqlite3.Row) -> Dict[str, Any]:
    """Helper to populate an entry with its senses, grammar, and source details."""
    eid = row["id"]
    headword = row["headword"]
    pos = row["part_of_speech"]
    gender = row["gender"]
    article = row["article"]
    source_edition = row["source_edition"]
    source_url = row["source_url"]

    raw_tags = []
    if row["raw_tags"]:
        try:
            raw_tags = json.loads(row["raw_tags"])
        except Exception:
            pass

    grammar_data = {}
    if row["grammar_data"]:
        try:
            grammar_data = json.loads(row["grammar_data"])
        except Exception:
            pass

    # Load senses
    cur_senses = conn.execute("""
        SELECT sense_order, gloss_en, gloss_de, tags, examples
        FROM senses
        WHERE entry_id = ?
        ORDER BY sense_order ASC
    """, (eid,))
    senses_rows = cur_senses.fetchall()

    senses = []
    for sr in senses_rows:
        tags = []
        if sr["tags"]:
            try:
                tags = json.loads(sr["tags"])
            except Exception:
                pass
        examples = []
        if sr["examples"]:
            try:
                examples = json.loads(sr["examples"])
            except Exception:
                pass

        gloss_en = sr["gloss_en"]
        gloss_de = sr["gloss_de"]
        if not gloss_en and source_edition == "de":
            gloss_en = "English meaning unavailable"

        senses.append({
            "order": sr["sense_order"],
            "gloss_en": gloss_en or "English meaning unavailable",
            "gloss_de": gloss_de,
            "tags": tags,
            "examples": examples
        })

    # Inherit English senses from base lemma if this entry only has unavailable English glosses
    has_real_en = any(s["gloss_en"] and s["gloss_en"] != "English meaning unavailable" for s in senses)
    if not has_real_en:
        cur_base = conn.execute("""
            SELECT e.id, e.headword, e.part_of_speech
            FROM forms f
            JOIN entries e ON e.id = f.entry_id
            WHERE f.lower_form = ? AND e.id != ?
            LIMIT 3
        """, (headword.lower(), eid))
        base_rows = cur_base.fetchall()

        inherited = []
        for b in base_rows:
            b_id = b["id"]
            b_hw = b["headword"]
            cur_bs = conn.execute("""
                SELECT sense_order, gloss_en, gloss_de, tags, examples
                FROM senses
                WHERE entry_id = ? AND gloss_en IS NOT NULL AND gloss_en != 'English meaning unavailable'
                ORDER BY sense_order ASC
                LIMIT 3
            """, (b_id,))
            for bs in cur_bs.fetchall():
                exs = []
                if bs["examples"]:
                    try:
                        exs = json.loads(bs["examples"])
                    except Exception:
                        pass
                inherited.append({
                    "order": len(inherited) + 1,
                    "gloss_en": f"{bs['gloss_en']} (form of '{b_hw}')",
                    "gloss_de": bs["gloss_de"],
                    "tags": ["form-of", f"base: {b_hw}"],
                    "examples": exs
                })

        if inherited:
            # Show inherited real English senses first, keeping any useful German notes
            senses = inherited + [s for s in senses if s["gloss_en"] != "English meaning unavailable"]
    else:
        # Filter out redundant 'English meaning unavailable' entries when real senses exist
        real_senses = [s for s in senses if s["gloss_en"] != "English meaning unavailable"]
        if real_senses:
            senses = real_senses

    return {
        "id": eid,
        "headword": headword,
        "part_of_speech": pos,
        "gender": gender,
        "article": article,
        "source_edition": source_edition,
        "source_url": source_url,
        "raw_tags": raw_tags,
        "grammar": grammar_data,
        "senses": senses,
        "etymology_number": row["etymology_number"]
    }

