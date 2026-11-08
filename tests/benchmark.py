#!/usr/bin/env python3
"""
Performance and Responsiveness Benchmark for Wortklar.
Measures warm suggestion latency on the full database with a representative query set.
Verifies the p95 latency requirement (< 200 ms).
"""

import os
import platform
import time
import statistics
import sqlite3

from wortklar.app import create_app
from wortklar.db import DEFAULT_DB_PATH, get_db_connection

REPRESENTATIVE_QUERY_SET = [
    "haus", "gehe", "lehr", "scho", "gute", "bess", "wass", "mens",
    "arbe", "fahr", "spie", "komm", "mach", "zeig", "nehm", "find",
    "wiss", "denk", "frag", "helf", "such", "blei", "wohn", "kauf",
    "verk", "star", "klei", "gros", "häus", "schö", "müde", "früh",
    "spät", "ging", "ginge", "hält", "nahm", "deut", "fran", "engl",
    "buche", "tisch", "stuh", "auto", "land", "stad", "freund", "kind"
]


def run_benchmark(db_path: str = DEFAULT_DB_PATH, iterations: int = 3):
    print("=" * 70)
    print(" Wortklar Performance Benchmark")
    print("=" * 70)
    print(f"Platform:         {platform.platform()}")
    print(f"Machine / Arch:   {platform.machine()}")
    print(f"Python Version:   {platform.python_version()}")
    print(f"Database Path:    {db_path}")

    if not os.path.exists(db_path):
        print(f"ERROR: Database file {db_path} not found. Run bootstrap.py first.")
        return False

    db_size_mb = os.path.getsize(db_path) / (1024 * 1024)
    print(f"Database Size:    {db_size_mb:.1f} MB")

    app = create_app(db_path=db_path)
    client = app.test_client()

    # 1. Warm-up run
    print("\n[Warmup] Warming up caches with initial queries...")
    for q in REPRESENTATIVE_QUERY_SET[:10]:
        client.get(f"/api/suggest?q={q}")

    # 2. Timed runs
    print(f"[Benchmark] Running {len(REPRESENTATIVE_QUERY_SET)} queries across {iterations} iterations...")
    timings = []

    for it in range(iterations):
        for q in REPRESENTATIVE_QUERY_SET:
            t0 = time.perf_counter()
            resp = client.get(f"/api/suggest?q={q}")
            t1 = time.perf_counter()
            assert resp.status_code == 200, f"Query '{q}' returned status {resp.status_code}"
            elapsed_ms = (t1 - t0) * 1000.0
            timings.append(elapsed_ms)

    timings.sort()
    n = len(timings)
    p50 = statistics.median(timings)
    p90 = timings[int(n * 0.90)]
    p95 = timings[int(n * 0.95)]
    p99 = timings[int(n * 0.99)]
    avg = statistics.mean(timings)
    min_t = min(timings)
    max_t = max(timings)

    print("\n" + "=" * 70)
    print(" Benchmark Results (Server-side Suggestion Latency)")
    print("=" * 70)
    print(f"Total Requests:   {n}")
    print(f"Min Latency:      {min_t:.2f} ms")
    print(f"Average:          {avg:.2f} ms")
    print(f"Median (p50):     {p50:.2f} ms")
    print(f"p90 Latency:      {p90:.2f} ms")
    print(f"p95 Latency:      {p95:.2f} ms")
    print(f"p99 Latency:      {p99:.2f} ms")
    print(f"Max Latency:      {max_t:.2f} ms")
    print("=" * 70)

    target_met = p95 < 200.0
    if target_met:
        print(f"SUCCESS: p95 latency ({p95:.2f} ms) is well UNDER the 200 ms target!")
    else:
        print(f"FAILURE: p95 latency ({p95:.2f} ms) EXCEEDS the 200 ms target!")

    return target_met


if __name__ == "__main__":
    run_benchmark()

