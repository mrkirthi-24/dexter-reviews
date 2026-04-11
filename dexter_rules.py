import os

MAX_RULES_CHARS = 12000
RULES_PATH = os.path.join(".github", "workflows", "DEXTER_RULES.md")


def load_project_rules(repo_root: str = ".", max_chars: int = MAX_RULES_CHARS) -> tuple[str | None, str | None]:
    """
    Load repository-specific Dexter rules.

    Returns a tuple of:
    - rules text (or None if missing/empty)
    - warning message for caller to surface (or None)
    """
    rules_file = os.path.join(repo_root, RULES_PATH)
    if not os.path.isfile(rules_file):
        return None, None

    with open(rules_file, encoding="utf-8") as f:
        content = f.read().replace("\r\n", "\n").strip()

    if not content:
        return None, f"Dexter rules file is empty: {RULES_PATH}"

    if len(content) > max_chars:
        truncated = content[:max_chars].rstrip()
        return (
            f"{truncated}\n\n[... truncated by Dexter ...]",
            f"Dexter rules file exceeded {max_chars} chars and was truncated: {RULES_PATH}",
        )

    return content, None
