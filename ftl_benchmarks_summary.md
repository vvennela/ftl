# FTL Benchmark Results — 2026-04-11

## Executive Summary

Real Docker-backed warm task overhead measured **291.44ms** on this machine, with **134.27ms** spent in workspace refresh and **95.87ms** in changed-file diffing. These numbers reflect a machine with Docker already running and the image already present; they do **not** capture worst-case first-user cold start, which can spike materially higher on a cold machine. The credential linter detected **70% of planted credential patterns** with a **0% false positive rate**. Destructive operation detection caught **90%** of planted patterns. Shadow key generation produced **0 collisions** in 1,000 runs. The real credential exposure surface spans **41 locations across 3 files** — exactly the expected handler set.

---

## 1. Real Docker-backed Latency

| Operation | Result |
|---|---|
| Cold boot, first measured sample | 1845.42ms |
| Cold boot, measured FTL boot path (mean) | 611.14ms |
| Cold boot, measured steady after first run (mean) | 302.57ms |
| Warm exec (mean) | 66.33ms |
| Prepare / workspace refresh (mean) | 134.27ms |
| Diff, no change (mean) | 138.4ms |
| Diff, no change steady after first run (mean) | 130.21ms |
| Diff, 5 changed files (mean) | 95.87ms |
| Warm task loop: prepare + edit + diff (mean) | 291.44ms |

The cold-boot rows above are the **full FTL boot path** with Docker already available. They should not be compared directly to raw Docker engine timings. The first measured sample is broken out separately because it often captures the one-time startup spike that averages hide, but it still does not represent the absolute worst case of a cold daemon plus missing image.

## 2. Local Primitive Latency

| Operation | Small | Medium | Large |
|---|---|---|---|
| Snapshot creation (mean) | 9.1ms | 26.0ms | 224.7ms |
| Shadow injection (mean) | 0.1ms | 0.3ms | 0.5ms |
| Local diff computation (mean) | 1.2ms | 8.7ms | 96.8ms |
| Local merge copy (mean) | 2.0ms | 2.2ms | 11.2ms |

## 3. Shadow Credential System

| Metric | Result |
|---|---|
| Detection accuracy | 100.0% (24/24) |
| Key collisions (1000 runs) | 0 |
| Format conformance | 100.0% (100/100) |

## 4. Linter Accuracy

| Metric | Result |
|---|---|
| Credential detection rate | 70.0% (7/10) |
| False positive rate | 0.0% (0/20) |
| Destructive command detection | 90.0% (9/10) |

## 5. Docker Microbenchmarks (Appendix)

| Metric | Result |
|---|---|
| Image size | 1.96GB |
| Raw `docker run` startup (mean) | 102.22ms |
| Warm exec (mean) | 66.86ms |
| Idle RAM | 600KiB / 3.826GiB |

These are **Docker engine microbenchmarks**, not end-to-end FTL timings. The raw `docker run` number is lower than the full FTL boot path because it excludes workspace initialization, env setup, and sandbox bookkeeping.

## 6. Real Credential Exposure Surface

**41 locations across 3 files:** ftl/credentials.py, ftl/orchestrator.py, ftl/proxy.py

This is the minimal expected set — real credentials are loaded in `credentials.py`, mapped in `orchestrator.py`, and swapped in `proxy.py` only.

## 7. Reliability (20 runs each)

| Component | Success Rate | Notes |
|---|---|---|
| Snapshot creation | 20/20 | |
| Shadow map | 20/20 | |
| Linter | 20/20 | Deterministic: True |

---

## Key Findings

- Shadow injection is **sub-millisecond** regardless of project scale — the bottleneck is always rsync, not credential processing
- Linter false positive rate is **0%** — no safe placeholder strings were flagged
- Credential exposure surface is confined to **3 files** — no unexpected handlers were found
- The real warm-path cost is dominated by Docker round trips and workspace refresh, not shadow mapping or local diff primitives
- The image measured here is **1.96GB**, which is materially larger than earlier lighter builds and should be called out when comparing historical cold-start numbers

## N/A Items

- **Adversarial test generation quality** — requires live LLM API call
- **Proxy interception rate** — requires running proxy + test HTTPS server
- **Host filesystem isolation** — requires exec inside running container (out of scope for unit benchmark)
- **Absolute first-ever cold start on a cold machine** — not captured by this suite; the benchmark assumes Docker is already running and the image is already present
