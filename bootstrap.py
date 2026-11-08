#!/usr/bin/env python3
"""
Wortklar Bootstrap Script.
Downloads real dictionary data from Kaikki/Wiktextract (English Wiktionary edition
and German Wiktionary edition supplement) and builds the local SQLite database.

Usage:
    # Full bootstrap from Kaikki real datasets:
    python3 bootstrap.py

    # Bootstrap using already downloaded local archives:
    python3 bootstrap.py --file-en data/kaikki-german-en.jsonl.gz --file-de data/kaikki-german-de.jsonl.gz

    # Quick test bootstrap with bounded record count:
    python3 bootstrap.py --limit-en 50000 --limit-de 50000
"""

import argparse
import os
import sys
import time

from wortklar.importer import (
    DictionaryImporter,
    download_file_with_progress,
    compute_file_sha256,
    DEFAULT_EN_URL,
    DEFAULT_DE_URL,
    DEFAULT_DB_PATH
)


def main():
    parser = argparse.ArgumentParser(description="Bootstrap Wortklar dictionary database with real Wiktionary data.")
    parser.add_argument("--en-url", default=DEFAULT_EN_URL, help="URL for English Wiktionary German dataset")
    parser.add_argument("--de-url", default=DEFAULT_DE_URL, help="URL for German Wiktionary supplement dataset")
    parser.add_argument("--file-en", help="Path to local existing JSONL or gzip file for English edition")
    parser.add_argument("--file-de", help="Path to local existing JSONL or gzip file for German supplement")
    parser.add_argument("--db-path", default=DEFAULT_DB_PATH, help=f"Destination SQLite database (default: {DEFAULT_DB_PATH})")
    parser.add_argument("--data-dir", default="data", help="Directory for cached dataset downloads (default: data/)")
    parser.add_argument("--limit-en", type=int, default=None, help="Limit number of EN records to import")
    parser.add_argument("--limit-de", type=int, default=None, help="Limit number of DE records to import")
    parser.add_argument("--batch-size", type=int, default=5000, help="Insert batch size (default: 5000)")
    parser.add_argument("--no-de", action="store_true", help="Skip German Wiktionary supplement")
    parser.add_argument("--force-download", action="store_true", help="Force redownload even if local cache exists")

    args = parser.parse_args()

    os.makedirs(args.data_dir, exist_ok=True)
    t0 = time.time()

    print("=" * 70)
    print(" Wortklar Dictionary Bootstrap")
    print("=" * 70)

    # 1. Resolve English edition file
    en_file = args.file_en
    sha256_en = None
    snap_date_en = None

    if not en_file:
        en_cache = os.path.join(args.data_dir, "kaikki-german-en.jsonl.gz")
        if os.path.exists(en_cache) and not args.force_download:
            print(f"[Cache] Using existing English edition download: {en_cache}")
            en_file = en_cache
            sha256_en = compute_file_sha256(en_cache)
        else:
            print(f"[Download] Fetching English Wiktionary German dataset from:\n  {args.en_url}")
            sha256_en, snap_date_en = download_file_with_progress(args.en_url, en_cache)
            en_file = en_cache
    else:
        print(f"[Local] Using provided English edition file: {en_file}")
        sha256_en = compute_file_sha256(en_file)

    # 2. Resolve German edition file
    de_file = args.file_de
    sha256_de = None
    snap_date_de = None

    if not args.no_de:
        if not de_file:
            de_cache = os.path.join(args.data_dir, "kaikki-german-de.jsonl.gz")
            if os.path.exists(de_cache) and not args.force_download:
                print(f"[Cache] Using existing German supplement download: {de_cache}")
                de_file = de_cache
                sha256_de = compute_file_sha256(de_cache)
            else:
                print(f"[Download] Fetching German Wiktionary supplement dataset from:\n  {args.de_url}")
                try:
                    sha256_de, snap_date_de = download_file_with_progress(args.de_url, de_cache)
                    de_file = de_cache
                except Exception as ex:
                    print(f"[Warning] Could not download German supplement ({ex}). Proceeding with English edition only.")
                    de_file = None
        else:
            print(f"[Local] Using provided German supplement file: {de_file}")
            sha256_de = compute_file_sha256(de_file)

    # Metadata to record
    meta_info = {
        "edition_en": "English Wiktionary via Kaikki/Wiktextract",
        "url_en": args.en_url,
        "sha256_en": sha256_en,
        "snapshot_date_en": snap_date_en or "2026-10-30",
        "edition_de": "German Wiktionary via Kaikki/Wiktextract" if de_file else "None",
        "url_de": args.de_url if de_file else "None",
        "sha256_de": sha256_de or "None",
        "snapshot_date_de": snap_date_de or "2026-11-01"
    }

    # 3. Execute bounded-batch import
    importer = DictionaryImporter(db_path=args.db_path, batch_size=args.batch_size)
    summary = importer.run_import(
        en_file=en_file,
        de_file=de_file,
        limit_en=args.limit_en,
        limit_de=args.limit_de,
        meta_info=meta_info
    )

    print("\n" + "=" * 70)
    print(" Bootstrap Complete")
    print("=" * 70)
    print(f"Database:         {args.db_path} ({summary['db_size_bytes'] / (1024*1024):.1f} MB)")
    print(f"Total Lemmas:     {summary['lemma_count']:,}")
    print(f"Total Forms:      {summary['form_count']:,}")
    print(f"Search Index:     {summary['search_index_count']:,}")
    print(f"EN Records:       {summary['records_en']:,} (Skipped: {summary['skipped_en']:,})")
    print(f"DE Records:       {summary['records_de']:,} (Skipped: {summary['skipped_de']:,})")
    print(f"Total Time:       {time.time() - t0:.1f} seconds")
    print("=" * 70)


if __name__ == "__main__":
    main()

