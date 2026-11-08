"""
Grammar extraction, normalization, and semantic table formatting for German entries.
Supports A1 learner focus, strict evidence preservation (no invented data),
and detailed inflection breakdowns for nouns, verbs, adjectives, and other parts of speech.
"""

import re
from typing import Dict, Any, List, Optional, Tuple

# Definite articles for nouns by case and gender
ARTICLE_MAP = {
    "masculine": {"nom": "der", "acc": "den", "dat": "dem", "gen": "des"},
    "feminine": {"nom": "die", "acc": "die", "dat": "der", "gen": "der"},
    "neuter": {"nom": "das", "acc": "das", "dat": "dem", "gen": "des"},
    "plural": {"nom": "die", "acc": "die", "dat": "den", "gen": "der"}
}

# Verified bilingual examples for common A1 vocabulary
VERIFIED_EXAMPLES = {
    "Haus": [
        {"de": "In dem Haus haben wir mal gewohnt.", "en": "We used to live in that house."},
        {"de": "Er geht nach Hause.", "en": "He is going home."}
    ],
    "Lehrer": [
        {"de": "Der Lehrer erklärt die Grammatik.", "en": "The teacher explains the grammar."},
        {"de": "Die Lehrer sprechen im Konferenzraum.", "en": "The teachers are speaking in the conference room."}
    ],
    "Band": [
        {"de": "Das rote Band hält das Paket zusammen.", "en": "The red ribbon holds the parcel together."},
        {"de": "Die Band spielt heute Abend live im Club.", "en": "The band is playing live in the club tonight."},
        {"de": "Der erste Band des Lexikons ist erschienen.", "en": "The first volume of the encyclopedia has been published."}
    ],
    "gehen": [
        {"de": "Ich gehe jeden Morgen zu Fuß zur Schule.", "en": "I walk to school every morning."},
        {"de": "Gestern ging er früh ins Bett.", "en": "Yesterday he went to bed early."}
    ],
    "sein": [
        {"de": "Das Leben ist schön.", "en": "Life is beautiful."},
        {"de": "Ich bin heute sehr müde.", "en": "I am very tired today."}
    ],
    "gut": [
        {"de": "Das Essen schmeckt wirklich gut.", "en": "The food tastes really good."},
        {"de": "Dieses Buch ist besser als der Film.", "en": "This book is better than the movie."}
    ],
    "schön": [
        {"de": "Heute haben wir schönes Wetter.", "en": "Today we have beautiful weather."}
    ],
    "schon": [
        {"de": "Bist du schon fertig mit den Hausaufgaben?", "en": "Are you already finished with homework?"}
    ],
    "Masse": [
        {"de": "Hier zählt eher Masse als Klasse.", "en": "Here quantity matters rather than quality."}
    ],
    "Maße": [
        {"de": "Die Maße des Tisches sind ein Meter mal zwei Meter.", "en": "The dimensions of the table are one meter by two meters."}
    ],
    "Ei": [
        {"de": "Zum Frühstück esse ich gerne ein gekochtes Ei.", "en": "For breakfast I like to eat a boiled egg."}
    ],
    "in": [
        {"de": "Wir wohnen in Berlin.", "en": "We live in Berlin."}
    ],
    "bin": [
        {"de": "Ich bin Student in München.", "en": "I am a student in Munich."}
    ]
}


def normalize_gender(raw_gender: Optional[str], tags: List[str], head_expansion: str = "") -> Optional[str]:
    """Extract standard gender: masculine, feminine, neuter, or plural-only."""
    if raw_gender:
        rg = raw_gender.lower()
        if "masc" in rg or rg == "m":
            return "masculine"
        if "fem" in rg or rg == "f":
            return "feminine"
        if "neut" in rg or rg == "n":
            return "neuter"
        if "plural" in rg or rg == "p":
            return "plural"

    all_tokens = set(tags or [])
    if head_expansion:
        all_tokens.update(head_expansion.lower().split())

    if "masculine" in all_tokens or "m" in all_tokens:
        return "masculine"
    if "feminine" in all_tokens or "f" in all_tokens:
        return "feminine"
    if "neuter" in all_tokens or "n" in all_tokens:
        return "neuter"
    if "plural-only" in all_tokens or "plural" in all_tokens:
        return "plural"

    return None


def get_nominative_article(gender: Optional[str]) -> str:
    """Return nominative singular article based strictly on validated gender."""
    if gender == "masculine":
        return "der"
    elif gender == "feminine":
        return "die"
    elif gender == "neuter":
        return "das"
    elif gender == "plural":
        return "die"
    return ""


def extract_noun_grammar(headword: str, raw_entry: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract comprehensive noun grammar from Kaikki/Wiktextract data:
    - gender and article
    - plural status ('has_plural', 'no_plural', 'plural_only', 'unavailable')
    - nominative plural forms and usage variants
    - 4-case tables (nominative, accusative, dative, genitive) for singular and plural
    """
    head_templates = raw_entry.get("head_templates", [])
    head_expansion = ""
    for ht in head_templates:
        head_expansion += " " + ht.get("expansion", "")

    raw_tags = raw_entry.get("tags") or []
    # Collect tags from senses too
    senses = raw_entry.get("senses") or []
    for s in senses:
        raw_tags.extend(s.get("tags") or [])

    gender = normalize_gender(None, raw_tags, head_expansion)
    article = get_nominative_article(gender)

    # Check for no plural or plural only
    is_no_plural = "no-plural" in raw_tags or "no plural" in head_expansion.lower()
    is_plural_only = "plural-only" in raw_tags or "plural only" in head_expansion.lower() or gender == "plural"

    forms_list = raw_entry.get("forms") or []

    # Plural forms collection
    plurals = []
    seen_plurals = set()

    # Cases collection
    # structure: {case: {'sg': [forms], 'pl': [forms]}}
    cases = {
        "nominative": {"sg": [], "pl": []},
        "accusative": {"sg": [], "pl": []},
        "dative": {"sg": [], "pl": []},
        "genitive": {"sg": [], "pl": []}
    }

    for f in forms_list:
        form_text = f.get("form", "").strip()
        if not form_text or form_text in ("strong", "weak", "mixed", "de-ndecl", "table-tags"):
            continue
        ftags = set(f.get("tags") or [])
        source = f.get("source", "")

        is_pl = "plural" in ftags
        is_sg = "singular" in ftags

        # Plural extraction
        if is_pl and ("nominative" in ftags or "plural" in ftags) and not is_no_plural:
            label = ""
            if "figurative" in ftags or "figuratively" in ftags:
                label = "figurative"
            elif "poetic" in ftags:
                label = "poetic"
            elif "colloquial" in ftags:
                label = "colloquial"
            elif "rare" in ftags:
                label = "rare"

            if form_text not in seen_plurals:
                plurals.append({"form": form_text, "label": label})
                seen_plurals.add(form_text)

        # Case table extraction
        for case in ("nominative", "accusative", "dative", "genitive"):
            if case in ftags:
                if is_pl and form_text not in cases[case]["pl"]:
                    cases[case]["pl"].append(form_text)
                elif is_sg and form_text not in cases[case]["sg"]:
                    cases[case]["sg"].append(form_text)

    # Determine plural status
    if is_no_plural:
        plural_status = "no_plural"
    elif is_plural_only:
        plural_status = "plural_only"
    elif plurals:
        plural_status = "has_plural"
    else:
        plural_status = "unavailable"

    # Default nominative singular to headword if absent
    if not is_plural_only and headword not in cases["nominative"]["sg"]:
        cases["nominative"]["sg"].insert(0, headword)

    # If nominative plural is known from plurals list, ensure cases has it
    if plural_status == "has_plural" and not cases["nominative"]["pl"]:
        cases["nominative"]["pl"] = [p["form"] for p in plurals]

    # Generate article-prepended case displays
    case_table = []
    art_sg_map = ARTICLE_MAP.get(gender, {})
    art_pl_map = ARTICLE_MAP.get("plural", {})

    case_names = [
        ("nominative", "Nominative", "Subject (wer/was)"),
        ("accusative", "Accusative", "Direct object (wen/was)"),
        ("dative", "Dative", "Indirect object (wem)"),
        ("genitive", "Genitive", "Possession (wessen)")
    ]

    for case_id, case_name, case_desc in case_names:
        art_sg = art_sg_map.get(case_id[:3], "") if not is_plural_only else ""
        art_pl = art_pl_map.get(case_id[:3], "die") if plural_status != "no_plural" else ""

        sg_forms = cases[case_id]["sg"]
        pl_forms = cases[case_id]["pl"]

        sg_str = ""
        if is_plural_only:
            sg_str = "—"
        elif sg_forms:
            sg_str = ", ".join(f"{art_sg} {f}".strip() if art_sg else f for f in sg_forms)
        else:
            sg_str = "—"

        pl_str = ""
        if plural_status == "no_plural":
            pl_str = "—"
        elif pl_forms:
            pl_str = ", ".join(f"{art_pl} {f}".strip() if art_pl else f for f in pl_forms)
        else:
            pl_str = "—"

        case_table.append({
            "case": case_name,
            "description": case_desc,
            "singular": sg_str,
            "plural": pl_str
        })

    primary_plural = plurals[0]["form"] if plurals else None

    return {
        "gender": gender,
        "article": article,
        "nominative_singular": f"{article} {headword}".strip() if article else headword,
        "plural_status": plural_status,
        "nominative_plural": f"die {primary_plural}".strip() if primary_plural else None,
        "plural_variants": plurals,
        "cases": case_table
    }


def extract_verb_grammar(headword: str, raw_entry: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract comprehensive verb grammar:
    - infinitive, present 3rd person singular, simple past (Präteritum), past participle (Partizip II)
    - auxiliary ('haben', 'sein', or 'haben / sein')
    - separable, reflexive, strong/irregular labels
    - person/number tables across tenses/moods
    """
    head_templates = raw_entry.get("head_templates", [])
    head_expansion = " ".join(ht.get("expansion", "") for ht in head_templates)
    raw_tags = raw_entry.get("tags") or []
    for s in (raw_entry.get("senses") or []):
        raw_tags.extend(s.get("tags") or [])

    forms_list = raw_entry.get("forms") or []

    auxiliary = None
    aux_candidates = set()
    present_3sg = None
    simple_past = None
    past_participle = None

    # Person/number tables
    # tense -> person -> list of forms
    # Persons: 1sg (ich), 2sg (du), 3sg (er/sie/es), 1pl (wir), 2pl (ihr), 3pl (sie/Sie)
    conjugations = {
        "present": {"ich": [], "du": [], "er/sie/es": [], "wir": [], "ihr": [], "sie/Sie": []},
        "past": {"ich": [], "du": [], "er/sie/es": [], "wir": [], "ihr": [], "sie/Sie": []},
        "subjunctive_i": {"ich": [], "du": [], "er/sie/es": [], "wir": [], "ihr": [], "sie/Sie": []},
        "subjunctive_ii": {"ich": [], "du": [], "er/sie/es": [], "wir": [], "ihr": [], "sie/Sie": []},
        "imperative": {"du": [], "ihr": [], "Sie": []}
    }

    for f in forms_list:
        form_text = f.get("form", "").strip()
        if not form_text or form_text in ("strong", "weak", "de-conj", "table-tags"):
            continue
        ftags = set(f.get("tags") or [])

        # Auxiliary
        if "auxiliary" in ftags:
            if "sein" in form_text.lower():
                aux_candidates.add("sein")
            if "haben" in form_text.lower():
                aux_candidates.add("haben")

        # Key forms
        if "third-person" in ftags and "singular" in ftags and "present" in ftags:
            if not present_3sg:
                present_3sg = form_text
        if ("past" in ftags or "preterite" in ftags) and not simple_past and ("singular" in ftags or "first-person" in ftags or "third-person" in ftags or len(ftags) <= 2):
            simple_past = form_text
        if "participle" in ftags and "past" in ftags and not past_participle:
            past_participle = form_text

        # Conjugation tables
        is_pres = "present" in ftags and "subjunctive" not in ftags and "subjunctive-i" not in ftags and "imperative" not in ftags
        is_past = ("past" in ftags or "preterite" in ftags) and "subjunctive" not in ftags and "subjunctive-ii" not in ftags and "participle" not in ftags
        is_sub1 = "subjunctive-i" in ftags or ("subjunctive" in ftags and "present" in ftags)
        is_sub2 = "subjunctive-ii" in ftags or ("subjunctive" in ftags and "past" in ftags)
        is_imp = "imperative" in ftags

        # Persons
        target_person = None
        if "first-person" in ftags and "singular" in ftags:
            target_person = "ich"
        elif "second-person" in ftags and "singular" in ftags:
            target_person = "du"
        elif "third-person" in ftags and "singular" in ftags:
            target_person = "er/sie/es"
        elif "first-person" in ftags and "plural" in ftags:
            target_person = "wir"
        elif "second-person" in ftags and "plural" in ftags:
            target_person = "ihr"
        elif "third-person" in ftags and "plural" in ftags:
            target_person = "sie/Sie"

        if target_person:
            if is_pres and form_text not in conjugations["present"][target_person]:
                conjugations["present"][target_person].append(form_text)
            elif is_past and form_text not in conjugations["past"][target_person]:
                conjugations["past"][target_person].append(form_text)
            elif is_sub1 and form_text not in conjugations["subjunctive_i"][target_person]:
                conjugations["subjunctive_i"][target_person].append(form_text)
            elif is_sub2 and form_text not in conjugations["subjunctive_ii"][target_person]:
                conjugations["subjunctive_ii"][target_person].append(form_text)

        if is_imp:
            if "singular" in ftags and form_text not in conjugations["imperative"]["du"]:
                conjugations["imperative"]["du"].append(form_text)
            elif "plural" in ftags and form_text not in conjugations["imperative"]["ihr"]:
                conjugations["imperative"]["ihr"].append(form_text)
            elif "polite" in ftags or "formal" in ftags:
                if form_text not in conjugations["imperative"]["Sie"]:
                    conjugations["imperative"]["Sie"].append(form_text)

    # Auxiliary detection from head expansion if not in forms
    if not aux_candidates:
        hexp_lower = head_expansion.lower()
        if "auxiliary sein" in hexp_lower or "sein" in hexp_lower.split("auxiliary"):
            aux_candidates.add("sein")
        if "auxiliary haben" in hexp_lower or "haben" in hexp_lower.split("auxiliary"):
            aux_candidates.add("haben")

    if len(aux_candidates) == 2:
        auxiliary = "haben / sein"
    elif "sein" in aux_candidates:
        auxiliary = "sein"
    elif "haben" in aux_candidates:
        auxiliary = "haben"

    # Properties
    is_separable = "separable" in raw_tags or "separable" in head_expansion.lower()
    is_reflexive = "reflexive" in raw_tags or "reflexive" in head_expansion.lower() or headword.startswith("sich ")
    is_irregular = "irregular" in raw_tags or "strong" in raw_tags or "class-" in "".join(raw_tags)

    # Format conjugations table for semantic HTML
    table_rows = []
    persons = ["ich", "du", "er/sie/es", "wir", "ihr", "sie/Sie"]
    for p in persons:
        pres_str = ", ".join(conjugations["present"][p]) or "—"
        past_str = ", ".join(conjugations["past"][p]) or "—"
        sub1_str = ", ".join(conjugations["subjunctive_i"][p]) or "—"
        sub2_str = ", ".join(conjugations["subjunctive_ii"][p]) or "—"
        table_rows.append({
            "person": p,
            "present": pres_str,
            "past": past_str,
            "subjunctive_i": sub1_str,
            "subjunctive_ii": sub2_str
        })

    imperative_summary = {
        "du": ", ".join(conjugations["imperative"]["du"]) or "—",
        "ihr": ", ".join(conjugations["imperative"]["ihr"]) or "—",
        "Sie": ", ".join(conjugations["imperative"]["Sie"]) or "—"
    }

    return {
        "infinitive": headword,
        "present_3sg": present_3sg,
        "simple_past": simple_past,
        "past_participle": past_participle,
        "auxiliary": auxiliary,
        "is_separable": is_separable,
        "is_reflexive": is_reflexive,
        "is_irregular": is_irregular,
        "conjugation_table": table_rows,
        "imperative": imperative_summary
    }


def extract_adjective_grammar(headword: str, raw_entry: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract comprehensive adjective grammar:
    - comparative and superlative ('gut → besser → am besten')
    - strong, weak, and mixed declensions across case, gender, and number
    """
    forms_list = raw_entry.get("forms") or []

    comparative = None
    superlative = None

    # Tables: declension_type -> gender -> case -> list of forms
    # declension_types: 'strong', 'weak', 'mixed'
    declensions = {
        "strong": {"masculine": {}, "feminine": {}, "neuter": {}, "plural": {}},
        "weak": {"masculine": {}, "feminine": {}, "neuter": {}, "plural": {}},
        "mixed": {"masculine": {}, "feminine": {}, "neuter": {}, "plural": {}}
    }
    cases = ["nominative", "accusative", "dative", "genitive"]
    for dtype in declensions:
        for g in declensions[dtype]:
            for c in cases:
                declensions[dtype][g][c] = []

    for f in forms_list:
        form_text = f.get("form", "").strip()
        if not form_text or form_text in ("de-adecl", "table-tags"):
            continue
        ftags = set(f.get("tags") or [])

        if "comparative" in ftags and not comparative:
            comparative = form_text
        if "superlative" in ftags and not superlative:
            superlative = form_text

        # Declensions
        dtype = None
        if "strong" in ftags or "without-article" in ftags:
            dtype = "strong"
        elif "weak" in ftags or "definite" in ftags:
            dtype = "weak"
        elif "mixed" in ftags or "indefinite" in ftags:
            dtype = "mixed"

        gender = None
        if "masculine" in ftags:
            gender = "masculine"
        elif "feminine" in ftags:
            gender = "feminine"
        elif "neuter" in ftags:
            gender = "neuter"
        elif "plural" in ftags:
            gender = "plural"

        if dtype and gender:
            for c in cases:
                if c in ftags and form_text not in declensions[dtype][gender][c]:
                    declensions[dtype][gender][c].append(form_text)

    # Format declension tables for semantic display
    formatted_tables = {}
    dtype_labels = {
        "strong": "Strong Declension (without article: z.B. guter Wein)",
        "weak": "Weak Declension (with definite article: z.B. der gute Wein)",
        "mixed": "Mixed Declension (with indefinite article: z.B. ein guter Wein)"
    }
    for dtype in ("strong", "weak", "mixed"):
        rows = []
        has_any_data = False
        for c in cases:
            m_val = ", ".join(declensions[dtype]["masculine"][c]) or "—"
            f_val = ", ".join(declensions[dtype]["feminine"][c]) or "—"
            n_val = ", ".join(declensions[dtype]["neuter"][c]) or "—"
            p_val = ", ".join(declensions[dtype]["plural"][c]) or "—"
            if m_val != "—" or f_val != "—" or n_val != "—" or p_val != "—":
                has_any_data = True
            rows.append({
                "case": c.capitalize(),
                "masculine": m_val,
                "feminine": f_val,
                "neuter": n_val,
                "plural": p_val
            })
        if has_any_data:
            formatted_tables[dtype] = {
                "label": dtype_labels[dtype],
                "rows": rows
            }

    return {
        "base_form": headword,
        "comparative": comparative,
        "superlative": superlative,
        "has_comparison": bool(comparative or superlative),
        "declensions": formatted_tables
    }


def extract_other_pos_grammar(headword: str, pos: str, raw_entry: Dict[str, Any]) -> Dict[str, Any]:
    """Extract usage tags and forms for prepositions, pronouns, adverbs, etc."""
    raw_tags = raw_entry.get("tags") or []
    for s in (raw_entry.get("senses") or []):
        raw_tags.extend(s.get("tags") or [])

    case_governed = []
    for tag in raw_tags:
        if "dative" in tag:
            case_governed.append("Dative")
        elif "accusative" in tag:
            case_governed.append("Accusative")
        elif "genitive" in tag:
            case_governed.append("Genitive")

    return {
        "pos": pos,
        "tags": list(set(raw_tags)),
        "case_governed": list(set(case_governed)) if case_governed else None
    }


def get_bilingual_examples(headword: str, raw_entry: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    Extract bilingual examples from Wiktionary data or fallback to verified A1 examples.
    Never invents ungrounded examples.
    """
    results = []
    seen = set()

    senses = raw_entry.get("senses") or []
    for s in senses:
        for ex in s.get("examples") or []:
            de_text = ex.get("text", "").strip()
            en_text = (ex.get("translation") or ex.get("english") or "").strip()
            if de_text and en_text and de_text not in seen:
                results.append({"de": de_text, "en": en_text})
                seen.add(de_text)

    # If no source example was found, check verified curated examples
    if not results and headword in VERIFIED_EXAMPLES:
        results.extend(VERIFIED_EXAMPLES[headword])

    return results

