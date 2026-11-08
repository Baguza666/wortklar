"""
Data download, validation, and database streaming importer for Wortklar.
Streams Kaikki English Wiktionary edition and German Wiktionary edition supplement,
records cryptographic checksums, snapshot dates, extraction gaps, and timings,
and atomically replaces the database only after integrity and count verifications succeed.
"""

import gzip
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import time
import urllib.request
from typing import Dict, Any, Optional, List, Tuple, Set

from wortklar.db import init_schema, set_metadata, check_integrity, DEFAULT_DB_PATH
from wortklar.grammar import (
    extract_noun_grammar,
    extract_verb_grammar,
    extract_adjective_grammar,
    extract_other_pos_grammar,
    get_bilingual_examples
)
from wortklar.search import fold_text, normalize_input

# Default source URLs
DEFAULT_EN_URL = "https://kaikki.org/dictionary/German/kaikki.org-dictionary-German.jsonl.gz"
DEFAULT_DE_URL = "https://kaikki.org/dewiktionary/Deutsch/kaikki.org-dictionary-Deutsch.jsonl.gz"


def download_file_with_progress(url: str, dest_path: str, chunk_size: int = 1024 * 1024) -> Tuple[str, Optional[str]]:
    """
    Stream download a file from url to dest_path, showing terminal progress.
    Computes and returns (sha256_hexdigest, snapshot_date).
    """
    os.makedirs(os.path.dirname(os.path.abspath(dest_path)), exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "WortklarBootstrap/1.0"})

    print(f"Connecting to: {url}")
    with urllib.request.urlopen(req) as resp:
        total_size = resp.headers.get("Content-Length")
        total_bytes = int(total_size) if total_size else None
        last_modified = resp.headers.get("Last-Modified")

        hasher = hashlib.sha256()
        downloaded = 0
        t0 = time.time()

        with open(dest_path, "wb") as f_out:
            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                f_out.write(chunk)
                hasher.update(chunk)
                downloaded += len(chunk)

                elapsed = time.time() - t0
                speed = (downloaded / (1024 * 1024)) / (elapsed if elapsed > 0 else 0.001)

                if total_bytes:
                    pct = (downloaded / total_bytes) * 100
                    sys.stdout.write(f"\r  Downloaded {downloaded / (1024*1024):.1f} MB / {total_bytes / (1024*1024):.1f} MB ({pct:.1f}%) at {speed:.2f} MB/s")
                else:
                    sys.stdout.write(f"\r  Downloaded {downloaded / (1024*1024):.1f} MB at {speed:.2f} MB/s")
                sys.stdout.flush()

    print(f"\nDownload finished in {time.time() - t0:.1f}s. SHA256: {hasher.hexdigest()[:16]}...")
    return hasher.hexdigest(), last_modified


def compute_file_sha256(file_path: str, chunk_size: int = 1024 * 1024) -> str:
    """Calculate SHA256 checksum of an existing local file."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


class DictionaryImporter:
    """Bounded-batch streaming importer into SQLite database."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH, batch_size: int = 5000):
        self.db_path = db_path
        self.tmp_db_path = db_path + ".tmp"
        self.batch_size = batch_size

        # Metrics
        self.records_en = 0
        self.records_de = 0
        self.skipped_en = 0
        self.skipped_de = 0
        self.lemmas_count = 0
        self.forms_count = 0

        # Memory tracking for fast deduplication / cross-referencing
        # (headword, pos) -> entry_id
        self.existing_entries: Dict[Tuple[str, str], int] = {}
        # (entry_id, form_text)
        self.existing_forms: Set[Tuple[int, str]] = set()

    def run_import(
        self,
        en_file: str,
        de_file: Optional[str] = None,
        limit_en: Optional[int] = None,
        limit_de: Optional[int] = None,
        meta_info: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Run full import into temporary database, verify integrity and counts,
        and atomically activate the database.
        """
        start_time = time.time()
        print(f"\n[Wortklar Importer] Initializing temporary database: {self.tmp_db_path}")

        if os.path.exists(self.tmp_db_path):
            os.remove(self.tmp_db_path)

        conn = sqlite3.connect(self.tmp_db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA synchronous = OFF")
        conn.execute("PRAGMA journal_mode = MEMORY")
        conn.execute("PRAGMA cache_size = -128000")  # 128 MB cache during import
        conn.execute("PRAGMA temp_store = MEMORY")
        init_schema(conn)

        try:
            # 1. Import English Wiktionary edition
            print(f"\n[1/2] Importing English Wiktionary German dataset from: {en_file}")
            self._import_english_edition(conn, en_file, limit=limit_en)

            # 2. Import German Wiktionary edition supplement if provided
            if de_file and os.path.exists(de_file):
                print(f"\n[2/2] Importing German Wiktionary supplement dataset from: {de_file}")
                self._import_german_supplement(conn, de_file, limit=limit_de)
            else:
                print("\n[2/2] German supplement omitted or file not provided.")

            # 3. Post-processing: link pending form entries to headwords
            print("\n[Post-Processing] Optimizing search index and verifying integrity...")
            conn.execute("PRAGMA optimize")

            # 4. Integrity check
            if not check_integrity(conn):
                raise RuntimeError("Temporary database failed SQLite integrity check!")

            cur = conn.execute("SELECT COUNT(*) FROM entries")
            total_lemmas = cur.fetchone()[0]
            cur = conn.execute("SELECT COUNT(*) FROM forms")
            total_forms = cur.fetchone()[0]
            cur = conn.execute("SELECT COUNT(*) FROM search_index")
            total_search_rows = cur.fetchone()[0]

            print(f"Database verification: {total_lemmas:,} lemmas, {total_forms:,} forms, {total_search_rows:,} search entries.")

            if total_lemmas == 0:
                raise RuntimeError("Zero entries imported! Import aborted.")

            # 5. Store Metadata
            elapsed = time.time() - start_time
            db_size = os.path.getsize(self.tmp_db_path)

            meta = {
                "records_en": self.records_en,
                "records_de": self.records_de,
                "skipped_en": self.skipped_en,
                "skipped_de": self.skipped_de,
                "lemma_count": total_lemmas,
                "form_count": total_forms,
                "search_index_count": total_search_rows,
                "elapsed_seconds": round(elapsed, 2),
                "db_size_bytes": db_size,
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            }
            if meta_info:
                meta.update(meta_info)

            for k, v in meta.items():
                set_metadata(conn, k, v)

            # Configure normal WAL mode before closing
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
            conn.close()

            # 6. Atomic activation
            print(f"\n[Activation] Atomically activating database: {self.db_path}")
            if os.path.exists(self.db_path):
                # Safe backup of previous good index
                backup_path = self.db_path + ".bak"
                shutil.copy2(self.db_path, backup_path)

            os.replace(self.tmp_db_path, self.db_path)
            print(f"[Done] Database activated successfully! Final size: {db_size / (1024*1024):.1f} MB in {elapsed:.1f}s.")
            return meta

        except Exception as e:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass
            if os.path.exists(self.tmp_db_path):
                os.remove(self.tmp_db_path)
            print(f"\n[Error] Import failed: {e}. Preserved previous good database.", file=sys.stderr)
            raise

    def _open_archive(self, file_path: str):
        """Open plain JSONL or gzipped JSONL."""
        if file_path.endswith(".gz"):
            return gzip.open(file_path, "rt", encoding="utf-8", errors="replace")
        return open(file_path, "r", encoding="utf-8", errors="replace")

    def _import_english_edition(self, conn: sqlite3.Connection, file_path: str, limit: Optional[int] = None):
        """Stream and parse English Wiktionary Kaikki snapshot."""
        t0 = time.time()
        batch_entries = []
        batch_senses = []
        batch_forms = []
        batch_search = []

        pending_form_refs = []  # forms needing entry_id lookup

        with self._open_archive(file_path) as f:
            for line_idx, line in enumerate(f):
                if limit and line_idx >= limit:
                    break
                line = line.strip()
                if not line:
                    continue

                try:
                    data = json.loads(line)
                except Exception:
                    self.skipped_en += 1
                    continue

                lang_code = data.get("lang_code")
                lang = data.get("lang")
                if lang_code and lang_code != "de" and lang != "German":
                    self.skipped_en += 1
                    continue

                word = normalize_input(data.get("word", ""))
                pos = data.get("pos", "").lower().strip()
                if not word or not pos:
                    self.skipped_en += 1
                    continue

                self.records_en += 1

                # Check if this record is a pure inflected form entry (e.g. ging, Häuser, bin)
                senses = data.get("senses") or []
                is_pure_form_record = False
                form_of_targets = []
                for s in senses:
                    form_of = s.get("form_of") or []
                    for fo in form_of:
                        target = fo.get("word")
                        if target:
                            form_of_targets.append((target, s.get("tags") or [], s.get("glosses") or []))
                            is_pure_form_record = True

                if is_pure_form_record and not any(len(s.get("glosses", [])) > 0 and not s.get("form_of") for s in senses):
                    # Save form reference for linking
                    for target_word, ftags, fglosses in form_of_targets:
                        pending_form_refs.append({
                            "form": word,
                            "target_word": normalize_input(target_word),
                            "pos": pos,
                            "tags": ftags,
                            "glosses": fglosses
                        })
                    continue

                # Process lemma entry
                grammar_data = {}
                if pos == "noun":
                    grammar_data = extract_noun_grammar(word, data)
                elif pos == "verb":
                    grammar_data = extract_verb_grammar(word, data)
                elif pos == "adj":
                    grammar_data = extract_adjective_grammar(word, data)
                else:
                    grammar_data = extract_other_pos_grammar(word, pos, data)

                gender = grammar_data.get("gender")
                article = grammar_data.get("article")
                raw_tags = data.get("tags") or []
                etym_num = data.get("etymology_number")
                source_url = f"https://en.wiktionary.org/wiki/{word}"

                # Insert entry row
                cur = conn.execute("""
                    INSERT INTO entries (headword, part_of_speech, gender, article, source_edition,
                                         source_url, raw_tags, grammar_data, etymology_number)
                    VALUES (?, ?, ?, ?, 'en', ?, ?, ?, ?)
                """, (word, pos, gender, article, source_url, json.dumps(raw_tags), json.dumps(grammar_data), etym_num))
                entry_id = cur.lastrowid
                self.lemmas_count += 1
                self.existing_entries[(word, pos)] = entry_id

                # Senses and bilingual examples
                examples = get_bilingual_examples(word, data)
                first_meaning = ""

                for s_idx, s in enumerate(senses):
                    glosses = s.get("glosses") or []
                    gloss_en = "; ".join(glosses).strip()
                    if not first_meaning and gloss_en:
                        first_meaning = gloss_en

                    s_tags = s.get("tags") or []
                    s_examples = []
                    # Attach source example if present on this sense
                    for ex in (s.get("examples") or []):
                        de_t = ex.get("text", "").strip()
                        en_t = (ex.get("translation") or ex.get("english") or "").strip()
                        if de_t and en_t:
                            s_examples.append({"de": de_t, "en": en_t})

                    # If this is the first sense and no source examples on sense, attach curated examples
                    if s_idx == 0 and not s_examples and examples:
                        s_examples = examples[:2]

                    batch_senses.append((
                        entry_id,
                        s_idx + 1,
                        gloss_en or None,
                        None,  # gloss_de
                        json.dumps(s_tags),
                        json.dumps(s_examples)
                    ))

                # Headword search index row
                preview = f"{article} {word} • {pos}." if article and pos == "noun" else f"{word} • {pos}."
                if first_meaning:
                    preview += f" {first_meaning[:60]}"

                batch_search.append((
                    word,
                    word.lower(),
                    fold_text(word),
                    entry_id,
                    1,  # is_lemma
                    None,  # form_label
                    1,  # rank_priority
                    preview
                ))

                # Forms extraction
                forms_list = data.get("forms") or []
                for f_item in forms_list:
                    form_text = normalize_input(f_item.get("form", ""))
                    if not form_text or form_text in ("strong", "weak", "mixed", "de-ndecl", "de-conj", "de-adecl", "table-tags", "no-table-tags"):
                        continue

                    ftags = f_item.get("tags") or []
                    f_article = f_item.get("article")
                    if (entry_id, form_text) not in self.existing_forms:
                        self.existing_forms.add((entry_id, form_text))
                        self.forms_count += 1
                        batch_forms.append((
                            form_text,
                            form_text.lower(),
                            entry_id,
                            "inflection",
                            json.dumps(ftags),
                            f_article
                        ))

                        # Search index row for form
                        form_label = f"{form_text} → {word}"
                        batch_search.append((
                            form_text,
                            form_text.lower(),
                            fold_text(form_text),
                            entry_id,
                            0,  # is_lemma
                            form_label,
                            2,  # rank_priority
                            preview
                        ))

                # Flush batches
                if len(batch_senses) >= self.batch_size:
                    self._flush_batches(conn, batch_senses, batch_forms, batch_search)

                if self.records_en % 50000 == 0:
                    rate = self.records_en / (time.time() - t0)
                    sys.stdout.write(f"\r  Processed {self.records_en:,} EN records ({rate:.0f} rec/s), {self.lemmas_count:,} lemmas")
                    sys.stdout.flush()

        # Final flush for EN edition
        self._flush_batches(conn, batch_senses, batch_forms, batch_search)

        # Link pending form references (e.g. ging -> gehen, Häuser -> Haus)
        print(f"\n  Resolving {len(pending_form_refs):,} dedicated form records...")
        linked_forms = 0
        for pref in pending_form_refs:
            f_word = pref["form"]
            t_word = pref["target_word"]
            f_pos = pref["pos"]
            # Look up entry_id for target_word
            target_eid = self.existing_entries.get((t_word, f_pos))
            if not target_eid:
                # Try just headword
                cur = conn.execute("SELECT id, part_of_speech FROM entries WHERE headword = ? LIMIT 1", (t_word,))
                r = cur.fetchone()
                if r:
                    target_eid = r["id"]

            if target_eid and (target_eid, f_word) not in self.existing_forms:
                self.existing_forms.add((target_eid, f_word))
                self.forms_count += 1
                linked_forms += 1
                conn.execute("""
                    INSERT INTO forms (form, lower_form, entry_id, form_type, tags, article)
                    VALUES (?, ?, ?, 'form_of', ?, NULL)
                """, (f_word, f_word.lower(), target_eid, json.dumps(pref["tags"])))

                form_label = f"{f_word} → {t_word}"
                conn.execute("""
                    INSERT INTO search_index (term, lower_term, folded_term, entry_id, is_lemma, form_label, rank_priority, preview)
                    VALUES (?, ?, ?, ?, 0, ?, 2, ?)
                """, (f_word, f_word.lower(), fold_text(f_word), target_eid, form_label, f"{t_word} • {f_pos}"))

        conn.commit()
        print(f"  Linked {linked_forms:,} form records. Total EN time: {time.time() - t0:.1f}s.")

    def _import_german_supplement(self, conn: sqlite3.Connection, file_path: str, limit: Optional[int] = None):
        """Stream and parse German Wiktionary supplement snapshot."""
        t0 = time.time()
        batch_senses = []
        batch_forms = []
        batch_search = []

        with self._open_archive(file_path) as f:
            for line_idx, line in enumerate(f):
                if limit and line_idx >= limit:
                    break
                line = line.strip()
                if not line:
                    continue

                try:
                    data = json.loads(line)
                except Exception:
                    self.skipped_de += 1
                    continue

                lang_code = data.get("lang_code")
                lang = data.get("lang")
                if lang_code and lang_code != "de" and lang != "Deutsch":
                    self.skipped_de += 1
                    continue

                word = normalize_input(data.get("word", ""))
                pos = data.get("pos", "").lower().strip()
                if not word or not pos:
                    self.skipped_de += 1
                    continue

                self.records_de += 1

                # Check if entry already exists from English edition
                existing_eid = self.existing_entries.get((word, pos))

                if existing_eid:
                    # Update source_edition to 'both' if not already
                    conn.execute("UPDATE entries SET source_edition = 'both' WHERE id = ?", (existing_eid,))

                    # Supplement additional forms from German Wiktionary
                    for f_item in (data.get("forms") or []):
                        form_text = normalize_input(f_item.get("form", ""))
                        if not form_text or form_text in ("strong", "weak", "table-tags", "inflection-template"):
                            continue
                        if (existing_eid, form_text) not in self.existing_forms:
                            self.existing_forms.add((existing_eid, form_text))
                            self.forms_count += 1
                            ftags = f_item.get("tags") or []
                            batch_forms.append((
                                form_text,
                                form_text.lower(),
                                existing_eid,
                                "de_supplement",
                                json.dumps(ftags),
                                f_item.get("article")
                            ))
                            form_label = f"{form_text} → {word}"
                            batch_search.append((
                                form_text,
                                form_text.lower(),
                                fold_text(form_text),
                                existing_eid,
                                0,
                                form_label,
                                3,  # lower priority than EN form
                                f"{word} • {pos}"
                            ))
                else:
                    # German-edition-only entry
                    # Look up English translations in translations array
                    translations = data.get("translations") or []
                    en_trans_by_sense: Dict[str, List[str]] = {}
                    for tr in translations:
                        if tr.get("lang_code") == "en" and tr.get("word"):
                            s_key = tr.get("sense", "default")
                            en_trans_by_sense.setdefault(s_key, []).append(tr["word"])

                    grammar_data = {}
                    if pos == "noun":
                        grammar_data = extract_noun_grammar(word, data)
                    elif pos == "verb":
                        grammar_data = extract_verb_grammar(word, data)
                    elif pos == "adj":
                        grammar_data = extract_adjective_grammar(word, data)
                    else:
                        grammar_data = extract_other_pos_grammar(word, pos, data)

                    gender = grammar_data.get("gender")
                    article = grammar_data.get("article")
                    raw_tags = data.get("tags") or []
                    source_url = f"https://de.wiktionary.org/wiki/{word}"

                    cur = conn.execute("""
                        INSERT INTO entries (headword, part_of_speech, gender, article, source_edition,
                                             source_url, raw_tags, grammar_data, etymology_number)
                        VALUES (?, ?, ?, ?, 'de', ?, ?, ?, NULL)
                    """, (word, pos, gender, article, source_url, json.dumps(raw_tags), json.dumps(grammar_data)))
                    entry_id = cur.lastrowid
                    self.lemmas_count += 1
                    self.existing_entries[(word, pos)] = entry_id

                    senses = data.get("senses") or []
                    first_meaning = ""

                    for s_idx, s in enumerate(senses):
                        de_gloss = "; ".join(s.get("glosses") or []).strip()
                        # Map English translations if available for this sense
                        sense_idx = s.get("sense_index", "")
                        en_gloss = None
                        if sense_idx and sense_idx in en_trans_by_sense:
                            en_gloss = "; ".join(en_trans_by_sense[sense_idx])
                        elif "default" in en_trans_by_sense:
                            en_gloss = "; ".join(en_trans_by_sense["default"])

                        if not en_gloss:
                            en_gloss = "English meaning unavailable"

                        if not first_meaning and en_gloss != "English meaning unavailable":
                            first_meaning = en_gloss

                        s_tags = s.get("tags") or []
                        batch_senses.append((
                            entry_id,
                            s_idx + 1,
                            en_gloss,
                            de_gloss or None,
                            json.dumps(s_tags),
                            json.dumps([])
                        ))

                    preview = f"{article} {word} • {pos}." if article and pos == "noun" else f"{word} • {pos}."
                    if first_meaning:
                        preview += f" {first_meaning[:60]}"
                    else:
                        preview += " (English meaning unavailable)"

                    batch_search.append((
                        word,
                        word.lower(),
                        fold_text(word),
                        entry_id,
                        1,
                        None,
                        1,
                        preview
                    ))

                    # Forms
                    for f_item in (data.get("forms") or []):
                        form_text = normalize_input(f_item.get("form", ""))
                        if not form_text or form_text in ("strong", "weak", "table-tags"):
                            continue
                        if (entry_id, form_text) not in self.existing_forms:
                            self.existing_forms.add((entry_id, form_text))
                            self.forms_count += 1
                            batch_forms.append((
                                form_text,
                                form_text.lower(),
                                entry_id,
                                "de_form",
                                json.dumps(f_item.get("tags") or []),
                                f_item.get("article")
                            ))
                            batch_search.append((
                                form_text,
                                form_text.lower(),
                                fold_text(form_text),
                                entry_id,
                                0,
                                f"{form_text} → {word}",
                                2,
                                preview
                            ))

                if len(batch_senses) >= self.batch_size:
                    self._flush_batches(conn, batch_senses, batch_forms, batch_search)

                if self.records_de % 50000 == 0:
                    rate = self.records_de / (time.time() - t0)
                    sys.stdout.write(f"\r  Processed {self.records_de:,} DE records ({rate:.0f} rec/s), {self.lemmas_count:,} lemmas")
                    sys.stdout.flush()

        self._flush_batches(conn, batch_senses, batch_forms, batch_search)
        conn.commit()
        print(f"\n  Finished German supplement import in {time.time() - t0:.1f}s.")

    def _flush_batches(self, conn: sqlite3.Connection, batch_senses: list, batch_forms: list, batch_search: list):
        """Commit buffered records to SQLite."""
        with conn:
            if batch_senses:
                conn.executemany("""
                    INSERT INTO senses (entry_id, sense_order, gloss_en, gloss_de, tags, examples)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, batch_senses)
                batch_senses.clear()

            if batch_forms:
                conn.executemany("""
                    INSERT INTO forms (form, lower_form, entry_id, form_type, tags, article)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, batch_forms)
                batch_forms.clear()

            if batch_search:
                conn.executemany("""
                    INSERT INTO search_index (term, lower_term, folded_term, entry_id, is_lemma, form_label, rank_priority, preview)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, batch_search)
                batch_search.clear()

