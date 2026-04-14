#!/usr/bin/env python3
"""
Tag gardening — analyse and consolidate the memory tag vocabulary.

Subcommands:
    stats    — Tag vocabulary statistics (JSON output)
    similar  — Find duplicate/near-duplicate tag candidates
    merge    — Apply a merge plan to JSONL + vocabulary
    orphans  — Identify vocabulary ↔ JSONL mismatches

Part of the personal-assistant system. Designed to be called by the
/tags slash command during monthly gardening sessions.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

# -------------------------------------------------------------------------
# Paths
# -------------------------------------------------------------------------

PA_ROOT = Path(__file__).resolve().parent.parent
MEMORIES_JSONL = PA_ROOT / "data" / "memories" / "memories.jsonl"
VOCABULARY_FILE = PA_ROOT / "data" / "memories" / "tag-vocabulary.txt"
LOG_DIR = PA_ROOT / "data" / "logs"

# Also check the symlink path as a fallback
if not MEMORIES_JSONL.exists():
    MEMORIES_JSONL = PA_ROOT / "memories" / "memories.jsonl"
if not VOCABULARY_FILE.exists():
    VOCABULARY_FILE = PA_ROOT / "memories" / "tag-vocabulary.txt"


# -------------------------------------------------------------------------
# False positives for plural detection
# -------------------------------------------------------------------------

# Words ending in 's' that are NOT plurals of the stem.
PLURAL_EXCLUSIONS = frozenset({
    "access", "alias", "analysis", "atlas", "basis", "bias", "bonus",
    "bus", "campus", "canvas", "chaos", "class", "consensus",
    "corpus", "crisis", "cross", "debris", "diagnosis", "discuss",
    "emphasis", "focus", "fungus", "genesis", "hypothesis", "iris",
    "lass", "lens", "loss", "mass", "miss", "moss", "nexus",
    "nucleus", "oasis", "pass", "plus", "process", "progress",
    "radius", "series", "species", "status", "stress", "success",
    "synthesis", "synopsis", "terminus", "thesis", "this", "thus",
    "versus", "virus",
})


# -------------------------------------------------------------------------
# Data loading
# -------------------------------------------------------------------------

def load_memories() -> list[dict[str, Any]]:
    """Load all memories from the canonical JSONL file."""
    memories: list[dict[str, Any]] = []
    with open(MEMORIES_JSONL, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                memories.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return memories


def load_vocabulary() -> set[str]:
    """Load the tag vocabulary file."""
    if not VOCABULARY_FILE.exists():
        return set()
    lines = VOCABULARY_FILE.read_text(encoding="utf-8").splitlines()
    return {
        line.strip()
        for line in lines
        if line.strip() and not line.strip().startswith("#")
    }


def _get_tags(mem: dict[str, Any]) -> list[str]:
    """
    Get the tag list from a memory, using consistent field resolution.

    Prefers ``research_tags`` if the key exists (even if empty),
    falls back to ``tags`` only when ``research_tags`` is absent.
    """
    if "research_tags" in mem:
        return mem["research_tags"] or []
    return mem.get("tags") or []


def build_tag_counts(memories: list[dict[str, Any]]) -> Counter[str]:
    """Build a frequency counter of all tags across memories."""
    counts: Counter[str] = Counter()
    for mem in memories:
        for tag in _get_tags(mem):
            if tag:
                counts[tag.lower()] += 1
    return counts


# -------------------------------------------------------------------------
# Stats subcommand
# -------------------------------------------------------------------------

def cmd_stats(args: argparse.Namespace) -> None:
    """Output tag vocabulary statistics as JSON."""
    memories = load_memories()
    tag_counts = build_tag_counts(memories)
    vocab = load_vocabulary()

    unique_tags = set(tag_counts.keys())
    total_usages = sum(tag_counts.values())

    # Frequency distribution
    singletons = sum(1 for c in tag_counts.values() if c == 1)
    used_2_3 = sum(1 for c in tag_counts.values() if 2 <= c <= 3)
    used_4_10 = sum(1 for c in tag_counts.values() if 4 <= c <= 10)
    used_11_plus = sum(1 for c in tag_counts.values() if c >= 11)

    # Top tags
    top_20 = tag_counts.most_common(20)

    # Memories with no tags
    no_tags = sum(
        1 for mem in memories
        if not (mem.get("research_tags") or mem.get("tags"))
    )

    # Vocabulary mismatches
    orphaned_vocab = vocab - unique_tags
    missing_from_vocab = unique_tags - vocab

    result = {
        "total_memories": len(memories),
        "total_tag_usages": total_usages,
        "unique_tags": len(unique_tags),
        "singletons": singletons,
        "singleton_pct": round(
            singletons / len(unique_tags) * 100, 1
        ) if unique_tags else 0,
        "used_2_3": used_2_3,
        "used_4_10": used_4_10,
        "used_11_plus": used_11_plus,
        "top_20": [[tag, count] for tag, count in top_20],
        "memories_with_no_tags": no_tags,
        "vocab_file_count": len(vocab),
        "orphaned_vocab": len(orphaned_vocab),
        "missing_from_vocab": len(missing_from_vocab),
    }

    json.dump(result, sys.stdout, indent=2)
    print()  # trailing newline


# -------------------------------------------------------------------------
# Plural detection
# -------------------------------------------------------------------------

def find_plural_pairs(
    tag_set: set[str],
    tag_counts: Counter[str],
) -> list[dict[str, Any]]:
    """
    Find plural/singular pairs in the tag set.

    Checks -s, -es, -ies→-y suffix stripping against the tag set.
    Returns candidate groups sorted by combined usage (descending).
    """
    pairs: list[dict[str, Any]] = []
    seen: set[frozenset[str]] = set()

    for tag in sorted(tag_set):
        if tag in PLURAL_EXCLUSIONS:
            continue

        singular = None

        # -ies → -y (e.g., "libraries" → "library")
        # No PLURAL_EXCLUSIONS check on candidate — the suffix rule
        # is specific enough that false positives are rare.
        if tag.endswith("ies") and len(tag) > 4:
            candidate = tag[:-3] + "y"
            if candidate in tag_set and candidate != tag:
                singular = candidate

        # -ses, -xes, -zes, -ches, -shes → drop -es
        # No PLURAL_EXCLUSIONS check on candidate — the singular
        # form may legitimately end in 's' (e.g., "processes" → "process").
        elif re.search(r"(s|x|z|ch|sh)es$", tag) and len(tag) > 3:
            candidate = tag[:-2]
            if candidate in tag_set and candidate != tag:
                singular = candidate

        # Generic -s (but not -ss)
        elif (
            tag.endswith("s")
            and not tag.endswith("ss")
            and len(tag) > 2
        ):
            candidate = tag[:-1]
            if (
                candidate in tag_set
                and candidate != tag
                and candidate not in PLURAL_EXCLUSIONS
            ):
                singular = candidate

        if singular:
            pair_key = frozenset({singular, tag})
            if pair_key in seen:
                continue
            seen.add(pair_key)

            s_count = tag_counts.get(singular, 0)
            p_count = tag_counts.get(tag, 0)
            combined = s_count + p_count

            pairs.append({
                "type": "plural",
                "tags": [
                    [singular, s_count],
                    [tag, p_count],
                ],
                "suggested_winner": singular,
                "reason": (
                    f"singular preferred ({combined} total usages)"
                ),
                "confidence": "high",
                "combined_usage": combined,
            })

    # Sort by combined usage descending
    pairs.sort(key=lambda p: p["combined_usage"], reverse=True)
    return pairs


# -------------------------------------------------------------------------
# Levenshtein / similarity clustering
# -------------------------------------------------------------------------

def _similarity_ratio(a: str, b: str) -> float:
    """
    Compute string similarity ratio.

    Uses rapidfuzz if available (50x faster), falls back to difflib.
    """
    try:
        from rapidfuzz import fuzz  # type: ignore[import-untyped]
        return fuzz.ratio(a, b) / 100.0
    except ImportError:
        return SequenceMatcher(None, a, b).ratio()


def find_similar_tags(
    tag_set: set[str],
    tag_counts: Counter[str],
    threshold: float = 0.85,
) -> list[dict[str, Any]]:
    """
    Find near-duplicate tags using sorted-prefix + length-bounded comparison.

    Groups tags by their first 3 characters, then compares within each
    bucket. This reduces comparisons from O(n²) to a manageable level.
    """
    # Build prefix buckets
    buckets: dict[str, list[str]] = {}
    for tag in tag_set:
        prefix = tag[:3] if len(tag) >= 3 else tag
        buckets.setdefault(prefix, []).append(tag)

    candidates: list[dict[str, Any]] = []
    seen_pairs: set[frozenset[str]] = set()

    for _prefix, tags in buckets.items():
        if len(tags) < 2:
            continue
        tags_sorted = sorted(tags)
        for i, tag_a in enumerate(tags_sorted):
            for tag_b in tags_sorted[i + 1:]:
                # Length filter: skip if lengths differ too much
                max_len = max(len(tag_a), len(tag_b))
                if abs(len(tag_a) - len(tag_b)) > max_len * (1 - threshold):
                    continue

                pair_key = frozenset({tag_a, tag_b})
                if pair_key in seen_pairs:
                    continue

                ratio = _similarity_ratio(tag_a, tag_b)
                if ratio >= threshold:
                    seen_pairs.add(pair_key)
                    count_a = tag_counts.get(tag_a, 0)
                    count_b = tag_counts.get(tag_b, 0)

                    # Winner = higher usage
                    if count_a >= count_b:
                        winner, loser = tag_a, tag_b
                    else:
                        winner, loser = tag_b, tag_a

                    candidates.append({
                        "type": "similar",
                        "tags": [[tag_a, count_a], [tag_b, count_b]],
                        "suggested_winner": winner,
                        "reason": (
                            f"similarity {ratio:.0%}, "
                            f"higher usage wins "
                            f"({tag_counts[winner]} vs "
                            f"{tag_counts[loser]})"
                        ),
                        "confidence": "medium",
                        "combined_usage": count_a + count_b,
                        "similarity": round(ratio, 3),
                    })

    candidates.sort(key=lambda c: c["combined_usage"], reverse=True)
    return candidates


# -------------------------------------------------------------------------
# Prefix grouping
# -------------------------------------------------------------------------

def find_prefix_pairs(
    tag_set: set[str],
    tag_counts: Counter[str],
    min_count: int = 2,
) -> list[dict[str, Any]]:
    """
    Find tags where one is a prefix of the other.

    Only flags pairs where both tags have usage >= min_count
    (singletons are noise, not prefix issues).
    """
    sorted_tags = sorted(tag_set)
    candidates: list[dict[str, Any]] = []

    for i in range(len(sorted_tags) - 1):
        tag_a = sorted_tags[i]
        # Check subsequent tags that start with tag_a
        for j in range(i + 1, len(sorted_tags)):
            tag_b = sorted_tags[j]
            if not tag_b.startswith(tag_a + "-"):
                break  # sorted order means no more matches

            count_a = tag_counts.get(tag_a, 0)
            count_b = tag_counts.get(tag_b, 0)

            if count_a < min_count and count_b < min_count:
                continue

            # Prefer more specific if both significant;
            # shorter if longer is a singleton
            if count_b >= min_count and count_a >= min_count:
                # Both significant — flag for human review
                winner = tag_a if count_a >= count_b else tag_b
                reason = "both significant — needs human review"
            elif count_b < min_count:
                winner = tag_a
                reason = f"longer form is near-singleton ({count_b})"
            else:
                winner = tag_b
                reason = f"shorter form is near-singleton ({count_a})"

            candidates.append({
                "type": "prefix",
                "tags": [[tag_a, count_a], [tag_b, count_b]],
                "suggested_winner": winner,
                "reason": reason,
                "confidence": "low",
                "combined_usage": count_a + count_b,
            })

    candidates.sort(key=lambda c: c["combined_usage"], reverse=True)
    return candidates


# -------------------------------------------------------------------------
# Similar subcommand
# -------------------------------------------------------------------------

def cmd_similar(args: argparse.Namespace) -> None:
    """Find and output duplicate/near-duplicate tag candidates."""
    memories = load_memories()
    tag_counts = build_tag_counts(memories)
    tag_set = set(tag_counts.keys())

    # Run all three detection stages
    plurals = find_plural_pairs(tag_set, tag_counts)
    similar = find_similar_tags(tag_set, tag_counts)
    prefixes = find_prefix_pairs(tag_set, tag_counts)

    # Remove overlaps: if a pair appears in plurals, don't repeat
    # it in similar or prefix results
    plural_pairs = {
        frozenset(t[0] for t in group["tags"])
        for group in plurals
    }
    similar = [
        c for c in similar
        if frozenset(t[0] for t in c["tags"]) not in plural_pairs
    ]
    prefixes = [
        c for c in prefixes
        if frozenset(t[0] for t in c["tags"]) not in plural_pairs
    ]

    # Combine and limit
    top = args.top if args.top is not None else 30
    all_candidates = plurals[:top] + similar[:top] + prefixes[:top]

    result = {
        "plural_count": len(plurals),
        "similar_count": len(similar),
        "prefix_count": len(prefixes),
        "candidates": all_candidates,
    }

    if args.format == "text":
        _print_similar_text(result)
    else:
        json.dump(result, sys.stdout, indent=2)
        print()


def _print_similar_text(result: dict[str, Any]) -> None:
    """Human-readable text output for the similar subcommand."""
    print(
        f"Found: {result['plural_count']} plural pairs, "
        f"{result['similar_count']} near-duplicates, "
        f"{result['prefix_count']} prefix pairs\n"
    )

    for group in result["candidates"]:
        tags_str = " | ".join(
            f"{t[0]} ({t[1]})" for t in group["tags"]
        )
        print(
            f"  [{group['confidence'].upper():6s}] "
            f"[{group['type']:7s}] {tags_str}"
        )
        print(
            f"           → {group['suggested_winner']}  "
            f"({group['reason']})"
        )
    print()


# -------------------------------------------------------------------------
# Merge subcommand
# -------------------------------------------------------------------------

def cmd_merge(args: argparse.Namespace) -> None:
    """Apply a merge plan to JSONL and vocabulary."""
    plan_path = Path(args.plan)
    if not plan_path.exists():
        print(f"Error: plan file not found: {plan_path}", file=sys.stderr)
        sys.exit(1)

    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"Error: invalid JSON in plan file: {exc}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(plan, list):
        print(
            "Error: merge plan must be a JSON array.",
            file=sys.stderr,
        )
        sys.exit(1)

    if not plan:
        print("Empty merge plan — nothing to do.")
        return

    # Build replacement map
    replacements: dict[str, str] = {}
    for i, entry in enumerate(plan):
        if not isinstance(entry, dict):
            print(
                f"Error: plan entry {i} is not an object.",
                file=sys.stderr,
            )
            sys.exit(1)
        if "winner" not in entry or "losers" not in entry:
            print(
                f"Error: plan entry {i} missing 'winner' or "
                f"'losers' key.",
                file=sys.stderr,
            )
            sys.exit(1)
        winner = entry["winner"]
        for loser in entry["losers"]:
            if loser in replacements:
                print(
                    f"Warning: {loser} appears in multiple merge "
                    f"entries — using first winner ({replacements[loser]})",
                    file=sys.stderr,
                )
                continue
            replacements[loser] = winner

    print(
        f"Merge plan: {len(replacements)} tags to retire "
        f"→ {len(set(replacements.values()))} winners"
    )

    # Load and transform memories
    memories_touched = 0
    tags_replaced = 0
    lines: list[str] = []

    with open(MEMORIES_JSONL, "r", encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()
            if not stripped:
                lines.append(line)
                continue

            try:
                mem = json.loads(stripped)
            except json.JSONDecodeError:
                lines.append(line)
                continue

            # Determine which field holds tags (consistent with
            # _get_tags / build_tag_counts)
            tag_field = (
                "research_tags"
                if "research_tags" in mem
                else "tags"
            )
            tags = _get_tags(mem)
            if not tags:
                # Preserve original line to avoid reformatting noise
                lines.append(line)
                continue

            new_tags: list[str] = []
            changed = False
            for tag in tags:
                tag_lower = tag.lower()
                if tag_lower in replacements:
                    new_tags.append(replacements[tag_lower])
                    changed = True
                    tags_replaced += 1
                else:
                    new_tags.append(tag)

            if changed:
                # Deduplicate preserving order
                new_tags = list(dict.fromkeys(new_tags))
                mem[tag_field] = new_tags
                memories_touched += 1
                lines.append(
                    json.dumps(mem, ensure_ascii=False) + "\n"
                )
            else:
                # Preserve original line to avoid reformatting noise
                lines.append(line)

    print(
        f"  Memories affected: {memories_touched}\n"
        f"  Tag replacements: {tags_replaced}\n"
        f"  Tags retired: {len(replacements)}"
    )

    if args.dry_run:
        print("\n[DRY RUN] No files modified.")
        return

    # Atomic write: write to temp file, then rename.
    # Note: the extraction hook appends without locking, so there is
    # a narrow race window where appends between our read and rename
    # could be lost. This is acceptable for a manual monthly command —
    # run it when no active sessions are extracting memories.
    tmp_path = MEMORIES_JSONL.with_suffix(".jsonl.tmp")
    tmp_path.write_text("".join(lines), encoding="utf-8")
    os.rename(str(tmp_path), str(MEMORIES_JSONL))

    print(f"  Updated: {MEMORIES_JSONL}")

    # Update vocabulary file
    if VOCABULARY_FILE.exists():
        vocab = load_vocabulary()
        # Remove losers, add winners
        vocab -= set(replacements.keys())
        vocab |= set(replacements.values())
        # Write sorted
        sorted_vocab = sorted(vocab)
        VOCABULARY_FILE.write_text(
            "\n".join(sorted_vocab) + "\n",
            encoding="utf-8",
        )
        print(f"  Updated: {VOCABULARY_FILE} ({len(sorted_vocab)} tags)")

    # Log
    _log_merge(plan, memories_touched, tags_replaced)
    print("\nDone. Run sync-to-postgres.py to update PostgreSQL.")


def _log_merge(
    plan: list[dict[str, Any]],
    memories_touched: int,
    tags_replaced: int,
) -> None:
    """Append a log entry for the merge operation."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / "tag-gardening.log"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(log_file, "a", encoding="utf-8") as fh:
        fh.write(
            f"{timestamp} MERGE: {len(plan)} groups, "
            f"{memories_touched} memories, "
            f"{tags_replaced} replacements\n"
        )


# -------------------------------------------------------------------------
# Orphans subcommand
# -------------------------------------------------------------------------

def cmd_orphans(args: argparse.Namespace) -> None:
    """Identify vocabulary ↔ JSONL mismatches."""
    memories = load_memories()
    tag_counts = build_tag_counts(memories)
    vocab = load_vocabulary()
    used_tags = set(tag_counts.keys())

    orphaned = sorted(vocab - used_tags)
    missing = sorted(used_tags - vocab)

    print(f"Tags in vocabulary but unused in JSONL: {len(orphaned)}")
    if orphaned:
        for tag in orphaned[:50]:
            print(f"  - {tag}")
        if len(orphaned) > 50:
            print(f"  ... and {len(orphaned) - 50} more")

    print(f"\nTags in JSONL but missing from vocabulary: {len(missing)}")
    if missing:
        for tag in missing[:50]:
            print(f"  - {tag} ({tag_counts[tag]})")
        if len(missing) > 50:
            print(f"  ... and {len(missing) - 50} more")

    if args.action == "clean":
        if orphaned or missing:
            new_vocab = (vocab - set(orphaned)) | set(missing)
            sorted_vocab = sorted(new_vocab)
            VOCABULARY_FILE.write_text(
                "\n".join(sorted_vocab) + "\n",
                encoding="utf-8",
            )
            print(
                f"\nUpdated {VOCABULARY_FILE}: "
                f"removed {len(orphaned)} orphaned, "
                f"added {len(missing)} missing "
                f"({len(sorted_vocab)} total)"
            )
        else:
            print("\nVocabulary is clean — nothing to do.")


# -------------------------------------------------------------------------
# CLI
# -------------------------------------------------------------------------

def main() -> None:
    """Entry point for the tag gardening script."""
    parser = argparse.ArgumentParser(
        description="Tag gardening — analyse and consolidate the "
        "memory tag vocabulary.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # stats
    subparsers.add_parser(
        "stats",
        help="Tag vocabulary statistics (JSON output)",
    )

    # similar
    similar_parser = subparsers.add_parser(
        "similar",
        help="Find duplicate/near-duplicate tag candidates",
    )
    similar_parser.add_argument(
        "--top",
        type=int,
        default=30,
        help="Max candidates per detection type (default: 30)",
    )
    similar_parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="json",
        help="Output format (default: json)",
    )

    # merge
    merge_parser = subparsers.add_parser(
        "merge",
        help="Apply a merge plan to JSONL + vocabulary",
    )
    merge_parser.add_argument(
        "--plan",
        required=True,
        help="Path to merge plan JSON file",
    )
    merge_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without modifying files",
    )

    # orphans
    orphan_parser = subparsers.add_parser(
        "orphans",
        help="Identify vocabulary ↔ JSONL mismatches",
    )
    orphan_parser.add_argument(
        "--action",
        choices=["list", "clean"],
        default="list",
        help="Action: list mismatches or clean them (default: list)",
    )

    args = parser.parse_args()

    if args.command == "stats":
        cmd_stats(args)
    elif args.command == "similar":
        cmd_similar(args)
    elif args.command == "merge":
        cmd_merge(args)
    elif args.command == "orphans":
        cmd_orphans(args)


if __name__ == "__main__":
    main()
