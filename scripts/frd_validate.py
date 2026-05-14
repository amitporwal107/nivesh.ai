#!/usr/bin/env python3
"""FRD Validation & Version Registry.

Scans all docs/FRD_*.md files, validates source references, counts
requirements by status, and maintains docs/FRD_VERSION_REGISTRY.json
with doc versions that are independent of git history.

Versioning: MAJOR.MINOR.PATCH
  PATCH — requirement status changes (e.g. PARTIAL → IMPLEMENTED)
  MINOR — new requirement IDs added or IDs removed
  MAJOR — manual only via --bump major <frd_name>

Usage:
    python scripts/frd_validate.py               # full scan + update registry
    python scripts/frd_validate.py --silent      # only print on errors
    python scripts/frd_validate.py --report      # print report, no writes
    python scripts/frd_validate.py --bump minor FRD_V2_BACKEND
    python scripts/frd_validate.py --if-changed  # skip if no relevant changes
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT   = Path(__file__).resolve().parent.parent
DOCS_DIR    = REPO_ROOT / "docs"
REGISTRY    = DOCS_DIR / "FRD_VERSION_REGISTRY.json"
FRD_PATTERN = "FRD_*.md"

# Statuses that count as "done"
DONE_STATUSES   = {"IMPLEMENTED", "DONE", "COMPLETE", "COMPLETED"}
PARTIAL_STATUS  = {"PARTIAL", "SCAFFOLDED", "BUGGY"}
PENDING_STATUS  = {"NOT IMPLEMENTED", "NOT_IMPLEMENTED", "PLANNED", "DEFERRED",
                   "NOT STARTED", "NOT_STARTED", "DEPRECATED"}

# Matches FR-AUTH-001, FR-FE-SHELL-001, FR-FE-V2-001, FR-COP1-001, etc.
# Pattern: FR- + one or more UPPERCASE segments separated by hyphens + -NNN digits
REQ_ROW_RE = re.compile(
    r"^\|\s*(FR-[A-Z0-9][A-Z0-9_]*(?:-[A-Z][A-Z0-9_]*)*-\d+[A-Z]?)\s*\|(.+)",
    re.MULTILINE,
)

# Regex: Source: `path/to/file.py`, `another/path`
SOURCE_PATH_RE = re.compile(r"`((?:backend|frontend|docs|scripts|tests)/[^`\s]+)`")

# Regex: **Doc Version:** line (if present in the FRD)
DOC_VERSION_RE = re.compile(r"^\*\*Doc Version:\*\*\s*([\d]+\.[\d]+\.[\d]+)", re.MULTILINE)

COLORS = {
    "green":  "\033[92m",
    "yellow": "\033[93m",
    "red":    "\033[91m",
    "cyan":   "\033[96m",
    "bold":   "\033[1m",
    "reset":  "\033[0m",
}

def c(color: str, text: str) -> str:
    if not sys.stdout.isatty():
        return text
    return f"{COLORS[color]}{text}{COLORS['reset']}"


# ── FRD parsing ──────────────────────────────────────────────────────

def _detect_status_col(lines: list[str]) -> int | None:
    """Find Status column index in the Requirements Traceability table header.

    Only considers table headers where the first column is 'req id', 'id',
    or 'requirement id' — not gap-analysis tables that also have a Status col.
    """
    for line in lines:
        if "|" not in line:
            continue
        cols = [c.strip().lower() for c in line.split("|")[1:-1]]
        if not cols:
            continue
        # Only the traceability matrix has 'req id' / 'id' as its first column
        if cols[0] not in ("req id", "id", "requirement id", "req. id"):
            continue
        for i, col in enumerate(cols):
            if col in ("status", "impl status", "implementation status"):
                return i
    return None


def _parse_status_from_cols(cols: list[str], status_col: int | None) -> str:
    """Extract status from a row's columns list, with header-guided or heuristic fallback.

    `cols` is built from the data after the requirement ID, so it is offset by 1
    relative to the header column index. We subtract 1 accordingly.
    """
    all_statuses = DONE_STATUSES | PARTIAL_STATUS | PENDING_STATUS
    # 1. Header-guided: status_col is from the full header (ID col = 0),
    #    so data index = status_col - 1.
    if status_col is not None:
        data_idx = status_col - 1
        if 0 <= data_idx < len(cols):
            candidate = cols[data_idx].upper().strip()
            if candidate in all_statuses:
                return candidate
    # 2. Heuristic: scan all columns for a known status value
    for col in cols:
        upper = col.upper().strip()
        if upper in all_statuses:
            return upper
    return "UNKNOWN"


def parse_frd(path: Path) -> dict[str, Any]:
    """Extract requirements, statuses, and source paths from an FRD file."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    # Detect which column holds Status in the Requirements Index table header
    status_col = _detect_status_col(lines)

    requirements: dict[str, str] = {}   # req_id → status
    for m in REQ_ROW_RE.finditer(text):
        req_id = m.group(1).strip()
        rest   = m.group(2)
        cols   = [c.strip() for c in rest.split("|") if c.strip() != ""]
        status = _parse_status_from_cols(cols, status_col)
        requirements[req_id] = status

    source_paths: list[str] = SOURCE_PATH_RE.findall(text)
    # Deduplicate while preserving order
    seen: set[str] = set()
    unique_sources: list[str] = []
    for p in source_paths:
        if p not in seen:
            seen.add(p)
            unique_sources.append(p)

    doc_version = "1.0.0"
    vm = DOC_VERSION_RE.search(text)
    if vm:
        doc_version = vm.group(1)

    return {
        "requirements": requirements,
        "source_paths": unique_sources,
        "doc_version": doc_version,
    }


def check_source_paths(source_paths: list[str]) -> list[str]:
    """Return list of source path strings that do not exist on disk."""
    broken: list[str] = []
    for raw in source_paths:
        # Skip generic placeholder patterns like <svc>, <name>, etc.
        if "<" in raw or ">" in raw:
            continue
        # Strip trailing punctuation, line numbers, anchors
        clean = raw.rstrip(".,;:/").split("#")[0].split(":")[0]
        # Glob pattern (anywhere in path) — check parent directory exists
        if "*" in clean:
            parent = clean.rsplit("/", 1)[0] if "/" in clean else "."
            candidate = REPO_ROOT / parent
            if not candidate.exists():
                broken.append(raw)
        else:
            candidate = REPO_ROOT / clean
            if not candidate.exists():
                broken.append(raw)
    return broken


def count_by_status(requirements: dict[str, str]) -> dict[str, int]:
    counts = {"implemented": 0, "partial": 0, "pending": 0, "other": 0, "total": 0}
    for status in requirements.values():
        counts["total"] += 1
        if status in DONE_STATUSES:
            counts["implemented"] += 1
        elif status in PARTIAL_STATUS:
            counts["partial"] += 1
        elif status in PENDING_STATUS:
            counts["pending"] += 1
        else:
            counts["other"] += 1
    return counts


# ── Version helpers ──────────────────────────────────────────────────

def parse_semver(v: str) -> tuple[int, int, int]:
    parts = v.split(".")
    return int(parts[0]), int(parts[1]), int(parts[2])


def bump_version(current: str, level: str) -> str:
    major, minor, patch = parse_semver(current)
    if level == "major":
        return f"{major + 1}.0.0"
    if level == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


# ── Registry load/save ───────────────────────────────────────────────

def load_registry() -> dict[str, Any]:
    if REGISTRY.exists():
        return json.loads(REGISTRY.read_text(encoding="utf-8"))
    return {"schema_version": "1", "frds": {}}


def save_registry(registry: dict[str, Any]) -> None:
    registry["last_updated"] = datetime.now(timezone.utc).isoformat()
    REGISTRY.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")


def git_head_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO_ROOT, stderr=subprocess.DEVNULL,
        ).decode().strip()
    except Exception:
        return "unknown"


def changed_files_in_commit() -> list[str]:
    """Files changed in the most recent commit."""
    try:
        out = subprocess.check_output(
            ["git", "diff", "HEAD~1", "--name-only"],
            cwd=REPO_ROOT, stderr=subprocess.DEVNULL,
        ).decode().strip()
        return [f for f in out.splitlines() if f]
    except Exception:
        return []


def relevant_changes_exist() -> bool:
    """Return True if recent git changes touch code or FRD files."""
    files = changed_files_in_commit()
    for f in files:
        if (f.startswith("backend/") or f.startswith("frontend/")
                or f.startswith("docs/FRD_") or f.startswith("scripts/")):
            return True
    return False


# ── Core scan ────────────────────────────────────────────────────────

def scan_all_frds(
    verbose: bool = True,
    dry_run: bool = False,
) -> tuple[int, int]:
    """Scan FRDs, update registry, return (error_count, warning_count)."""
    registry = load_registry()
    sha       = git_head_sha()
    errors    = 0
    warnings  = 0
    changed   = False

    frd_files = sorted(DOCS_DIR.glob(FRD_PATTERN))
    if not frd_files:
        print(c("yellow", "No FRD_*.md files found in docs/"))
        return 0, 0

    if verbose:
        print(c("bold", f"\nFRD Validation Report — {datetime.now().strftime('%Y-%m-%d %H:%M')}"))
        print(c("bold", f"Commit: {sha}"))
        print("─" * 64)

    for frd_path in frd_files:
        name   = frd_path.stem
        parsed = parse_frd(frd_path)
        counts = count_by_status(parsed["requirements"])
        broken = check_source_paths(parsed["source_paths"])

        # Determine version bump needed
        prev_entry = registry["frds"].get(name, {})
        prev_counts = prev_entry.get("counts", {})
        prev_req_ids = set(prev_entry.get("requirement_ids", []))
        curr_req_ids = set(parsed["requirements"].keys())

        current_version = prev_entry.get("version", "1.0.0")
        bump_level = None

        if not prev_entry:
            bump_level = None  # first time — start at 1.0.0
        elif curr_req_ids != prev_req_ids:
            bump_level = "minor"  # IDs added/removed
        elif counts != prev_counts:
            bump_level = "patch"  # status counts changed

        new_version = current_version
        if bump_level and not dry_run:
            new_version = bump_version(current_version, bump_level)
            changed = True

        if verbose:
            pct = int(counts["implemented"] / counts["total"] * 100) if counts["total"] else 0
            bar_filled = pct // 5
            bar = "█" * bar_filled + "░" * (20 - bar_filled)
            ver_marker = f"  {c('yellow', f'↑{bump_level}')} → v{new_version}" if bump_level else ""
            print(
                f"{c('bold', name):<35}  v{current_version:<7}{ver_marker}\n"
                f"  [{bar}] {pct:3d}%  "
                f"{c('green', str(counts['implemented']))} impl  "
                f"{c('yellow', str(counts['partial']))} partial  "
                f"{c('red', str(counts['pending']))} pending  "
                f"({counts['total']} total)"
            )

        if broken:
            errors += len(broken)
            if verbose:
                for bp in broken:
                    print(f"  {c('red', '✗ broken source ref:')} {bp}")

        if not dry_run:
            registry["frds"][name] = {
                "version":         new_version,
                "file":            f"docs/{frd_path.name}",
                "last_validated":  datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "last_commit":     sha,
                "counts":          counts,
                "requirement_ids": sorted(curr_req_ids),
                "broken_refs":     broken,
            }

    if verbose:
        print("─" * 64)
        if errors:
            print(c("red", f"  {errors} broken source reference(s) — update FRD Source: fields"))
        else:
            print(c("green", "  All source references valid"))

    if not dry_run:
        save_registry(registry)
        if verbose:
            print(c("cyan", f"  Registry updated → {REGISTRY.relative_to(REPO_ROOT)}"))

    if verbose:
        print()

    return errors, warnings


# ── Manual version bump ──────────────────────────────────────────────

def manual_bump(level: str, frd_name: str) -> None:
    registry = load_registry()
    if frd_name not in registry["frds"]:
        print(f"Error: '{frd_name}' not in registry. Run without --bump first.")
        sys.exit(1)
    old = registry["frds"][frd_name]["version"]
    new = bump_version(old, level)
    registry["frds"][frd_name]["version"] = new
    registry["frds"][frd_name]["last_validated"] = \
        datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    save_registry(registry)
    print(f"{frd_name}: v{old} → v{new}  ({level} bump)")


# ── PR checklist check ───────────────────────────────────────────────

PR_CHECKLIST = [
    "Code updated",
    "Tests added",
    "Documentation updated",
    "API spec updated",
    "Release notes updated",
]

def check_pr_checklist_hint() -> None:
    """Print a reminder when code files changed but no FRD was touched."""
    changed = changed_files_in_commit()
    code_changed = any(
        f.startswith("backend/") or f.startswith("frontend/")
        for f in changed
    )
    frd_changed = any(f.startswith("docs/FRD_") for f in changed)
    if code_changed and not frd_changed:
        print(c("yellow", "\n⚠  Code changed but no FRD updated in this commit."))
        print(c("yellow", "   PR Checklist:"))
        for item in PR_CHECKLIST:
            print(f"   {'✓' if item == 'Code updated' else '○'}  {item}")
        print()


# ── Entry point ──────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description="Validate FRDs and maintain version registry.")
    ap.add_argument("--silent",     action="store_true", help="Only print on errors.")
    ap.add_argument("--report",     action="store_true", help="Print report; do not write registry.")
    ap.add_argument("--if-changed", action="store_true", help="Skip if no relevant files changed.")
    ap.add_argument("--bump",       nargs=2, metavar=("LEVEL", "FRD_NAME"),
                    help="Manually bump version. LEVEL: major|minor|patch")
    args = ap.parse_args()

    if args.bump:
        level, name = args.bump
        if level not in ("major", "minor", "patch"):
            print("Error: LEVEL must be major|minor|patch")
            sys.exit(1)
        manual_bump(level, name)
        return

    if args.if_changed and not relevant_changes_exist():
        return

    errors, _ = scan_all_frds(
        verbose=not args.silent,
        dry_run=args.report,
    )

    if not args.report:
        check_pr_checklist_hint()

    # Exit 0 regardless — never block a commit. Errors are warnings, not failures.
    sys.exit(0)


if __name__ == "__main__":
    main()
