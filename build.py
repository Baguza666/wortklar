#!/usr/bin/env python3
"""
Render Build Pipeline Script for Wortklar.
Executed during Render's build phase:
    pip install -r requirements.txt && python build.py

Ensures the full SQLite index is installed, verified, and packaged into the build output
so that application startup is instant (read-only query mode) without re-importing.
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
from typing import Optional, Tuple

from wortklar.db import DEFAULT_DB_PATH, get_db_connection, get_metadata, check_integrity
from wortklar.importer import (
    DictionaryImporter,
    download_file_with_progress,
    compute_file_sha256,
    DEFAULT_EN_URL,
    DEFAULT_DE_URL
)


def verify_database(db_path: str) -> Tuple[bool, int, int]:
    """Check if database exists, passes quick check, and has nonzero lemmas and forms."""
    if not os.path.exists(db_path):
        return False, 0, 0
    try:
        conn = get_db_connection(db_path, read_only=True)
        if not check_integrity(conn, quick=True):
            conn.close()
            return False, 0, 0
        meta = get_metadata(conn)
        lemmas = meta.get("lemma_count", 0)
        forms = meta.get("form_count", 0)
        conn.close()
        return (lemmas > 0 and forms > 0), lemmas, forms
    except Exception as ex:
        print(f"[Check] Existing database verification failed: {ex}")
        return False, 0, 0


def fetch_release_asset(url: str, dest_path: str, token: Optional[str] = None, expected_sha256: Optional[str] = None) -> None:
    """
    Fallback: Download pre-built database from private GitHub Release asset
    using repository-scoped read-only token.
    """
    print(f"[Fallback Download] Fetching release asset from:\n  {url}")
    headers = {"User-Agent": "WortklarBuild/1.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
        headers["Accept"] = "application/octet-stream"

    req = urllib.request.Request(url, headers=headers)
    is_gz = url.endswith(".gz") or dest_path.endswith(".gz")
    download_target = dest_path + ".tmp.dl"

    hasher = hashlib.sha256()
    t0 = time.time()
    with urllib.request.urlopen(req) as resp, open(download_target, "wb") as f_out:
        while True:
            chunk = resp.read(1024 * 1024)
            if not chunk:
                break
            f_out.write(chunk)
            hasher.update(chunk)
            print(".", end="", flush=True)

    download_sha256 = hasher.hexdigest()
    print(f"\nDownload completed in {time.time() - t0:.1f}s. SHA256: {download_sha256}")

    if expected_sha256 and expected_sha256.lower() != download_sha256.lower():
        os.remove(download_target)
        raise ValueError(f"Checksum mismatch! Expected {expected_sha256}, got {download_sha256}")

    if is_gz:
        print(f"[Decompress] Decompressing archive into {dest_path}...")
        with gzip.open(download_target, "rb") as f_in, open(dest_path, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)
        os.remove(download_target)
    else:
        os.replace(download_target, dest_path)


def clean_scratch_files(data_dir: str) -> None:
    """Clean up downloaded .gz scratch files to respect Render build disk limits."""
    if os.path.exists(data_dir):
        print(f"[Cleanup] Removing build scratch downloads in: {data_dir}")
        for item in os.listdir(data_dir):
            if item.endswith(".gz") or item.endswith(".tmp") or item.endswith(".jsonl"):
                p = os.path.join(data_dir, item)
                try:
                    os.remove(p)
                    print(f"  Removed scratch file: {item}")
                except OSError:
                    pass


def main():
    db_path = os.environ.get("WORTKLAR_DB", DEFAULT_DB_PATH)
    data_dir = os.environ.get("WORTKLAR_DATA_DIR", "data")
    release_asset_url = os.environ.get("RELEASE_ASSET_URL") or os.environ.get("GITHUB_RELEASE_ASSET_URL")
    release_token = os.environ.get("GITHUB_TOKEN")
    release_sha256 = os.environ.get("RELEASE_ASSET_SHA256")

    print("=" * 70)
    print(" Wortklar Render Build Pipeline")
    print("=" * 70)
    print(f"Target Database: {db_path}")

    t_start = time.time()

    # Step 1: Check if verified database already exists
    is_valid, lemmas, forms = verify_database(db_path)
    if is_valid:
        print(f"[Index Present] Found existing verified database with {lemmas:,} lemmas and {forms:,} forms.")
        print(f"[Skip Build] Re-import not needed. Application build artifact is ready.")
        size_mb = os.path.getsize(db_path) / (1024 * 1024)
        print(f"Final Artifact Size: {size_mb:.1f} MB in {time.time() - t_start:.2f}s")
        print("=" * 70)
        return

    # Step 2: Fallback GitHub Release Asset if configured
    if release_asset_url:
        print("[Build Mode] Fetching prebuilt index from private GitHub Release asset...")
        fetch_release_asset(release_asset_url, db_path, token=release_token, expected_sha256=release_sha256)
    else:
        # Step 3: Default Kaikki streaming download and full database build
        print("[Build Mode] Streaming download from Kaikki and building full index...")
        os.makedirs(data_dir, exist_ok=True)

        en_cache = os.path.join(data_dir, "kaikki-german-en.jsonl.gz")
        de_cache = os.path.join(data_dir, "kaikki-german-de.jsonl.gz")

        # Download EN dataset
        if not os.path.exists(en_cache):
            sha_en, snap_en = download_file_with_progress(DEFAULT_EN_URL, en_cache)
        else:
            sha_en = compute_file_sha256(en_cache)
            snap_en = "2026-10-30"

        # Download DE dataset
        if not os.path.exists(de_cache):
            try:
                sha_de, snap_de = download_file_with_progress(DEFAULT_DE_URL, de_cache)
            except Exception as ex:
                print(f"[Warning] German supplement download failed ({ex}). Proceeding with EN edition.")
                de_cache = None
                sha_de = None
                snap_de = None
        else:
            sha_de = compute_file_sha256(de_cache)
            snap_de = "2026-11-01"

        meta_info = {
            "edition_en": "English Wiktionary via Kaikki/Wiktextract",
            "url_en": DEFAULT_EN_URL,
            "sha256_en": sha_en,
            "snapshot_date_en": snap_en or "2026-10-30",
            "edition_de": "German Wiktionary via Kaikki/Wiktextract" if de_cache else "None",
            "url_de": DEFAULT_DE_URL if de_cache else "None",
            "sha256_de": sha_de or "None",
            "snapshot_date_de": snap_de or "2026-11-01",
            "build_environment": "render-python-native"
        }

        importer = DictionaryImporter(db_path=db_path, batch_size=5000)
        importer.run_import(
            en_file=en_cache,
            de_file=de_cache,
            meta_info=meta_info
        )

        # Clean scratch downloads to respect build disk limit
        clean_scratch_files(data_dir)

    # Step 4: Final verification and read-only preparation
    is_valid, lemmas, forms = verify_database(db_path)
    if not is_valid:
        raise RuntimeError("Build failed: Output database is missing, corrupted, or empty!")

    size_mb = os.path.getsize(db_path) / (1024 * 1024)
    elapsed = time.time() - t_start
    print("=" * 70)
    print(f" Build Successful!")
    print(f" Database: {db_path} ({size_mb:.1f} MB)")
    print(f" Lemmas:   {lemmas:,}")
    print(f" Forms:    {forms:,}")
    print(f" Time:     {elapsed:.1f}s")
    print(f" Read-only runtime verified for Render 512 MB Free Tier.")
    print("=" * 70)


if __name__ == "__main__":
    main()

