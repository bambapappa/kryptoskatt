"""Verify migration chain integrity."""

import re
from pathlib import Path

VERSIONS_DIR = Path(__file__).parent.parent / "alembic" / "versions"


def _load_migration_metadata() -> list[dict]:
    """Read each migration file and extract revision / down_revision via regex."""
    entries = []
    for path in sorted(VERSIONS_DIR.glob("*.py")):
        if path.name.startswith("__"):
            continue
        text = path.read_text()

        rev_match = re.search(r'^revision\s*(?::\s*str\s*)?=\s*["\']([^"\']+)["\']', text, re.MULTILINE)
        down_match = re.search(r'^down_revision\s*(?::[^=]+)?\s*=\s*["\']([^"\']+)["\']', text, re.MULTILINE)

        if rev_match:
            entries.append(
                {
                    "file": path.name,
                    "revision": rev_match.group(1),
                    "down_revision": down_match.group(1) if down_match else None,
                }
            )
    return entries


def test_migration_chain_is_complete() -> None:
    """All migrations form a single linear chain from root (None) to HEAD with no cycles."""
    entries = _load_migration_metadata()
    assert entries, "No migration files found"

    # Build revision -> down_revision map
    rev_to_down: dict[str, str | None] = {e["revision"]: e["down_revision"] for e in entries}
    all_revisions = set(rev_to_down.keys())

    # Exactly one root (down_revision = None)
    roots = [rev for rev, down in rev_to_down.items() if down is None]
    assert len(roots) == 1, (
        f"Expected exactly one root migration (down_revision=None), found {len(roots)}: {roots}"
    )

    # Build forward links: down_revision -> revision
    down_to_rev: dict[str | None, list[str]] = {}
    for rev, down in rev_to_down.items():
        down_to_rev.setdefault(down, []).append(rev)

    # Detect branches (more than one child)
    for down, children in down_to_rev.items():
        assert len(children) <= 1, (
            f"Branch detected: revision '{down}' has multiple children {children}"
        )

    # Walk the chain from root to verify all revisions are reachable
    visited: list[str] = []
    current: str | None = roots[0]
    while current is not None:
        assert current not in visited, f"Cycle detected at revision '{current}'"
        visited.append(current)
        children = down_to_rev.get(current, [])
        current = children[0] if children else None

    # Every revision must appear in the walk
    missing = all_revisions - set(visited)
    assert not missing, (
        f"Unreachable revisions (disconnected from chain): {missing}"
    )


def test_migration_chain_has_no_duplicate_revisions() -> None:
    """No two migration files share the same revision ID."""
    entries = _load_migration_metadata()
    seen: dict[str, str] = {}
    for e in entries:
        rev = e["revision"]
        assert rev not in seen, (
            f"Duplicate revision '{rev}' found in {e['file']} and {seen[rev]}"
        )
        seen[rev] = e["file"]


def test_migration_down_revisions_reference_existing_revisions() -> None:
    """Every down_revision (except None) points to a revision that actually exists."""
    entries = _load_migration_metadata()
    all_revisions = {e["revision"] for e in entries}
    for e in entries:
        down = e["down_revision"]
        if down is not None:
            assert down in all_revisions, (
                f"Migration {e['file']} references down_revision '{down}' "
                f"which does not exist in any migration file"
            )
