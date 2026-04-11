# review_demo.py
# Outside-Diff Impact Slicing: Find bugs by analyzing callers/callees around the diff.

import pathlib
import subprocess
import ast
import sys
from typing import Dict, Set, List, Tuple


class PythonParseError(Exception):
    """Raised when a .py file cannot be parsed for impact/call analysis."""


def _format_syntax_error(path: str, src: str, err: SyntaxError) -> str:
    lineno = err.lineno or 1
    line_body = (err.text or "").rstrip("\n")
    if not line_body:
        rows = src.splitlines()
        if 0 < lineno <= len(rows):
            line_body = rows[lineno - 1]
    col = err.offset
    caret = ""
    if col is not None and line_body:
        caret = " " * (col - 1) + "^"
    loc = f"line {lineno}"
    if col is not None:
        loc += f", column {col}"
    parts = [
        f"Invalid Python syntax in {path!r} ({loc}): {err.msg}",
        f"  {line_body}",
    ]
    if caret:
        parts.append(f"  {caret}")
    parts.append(
        "Dexter parses Python to map callers and callees around your diff; fix this syntax error, then re-run the review."
    )
    return "\n".join(parts)


def parse_python(path: str, src: str) -> ast.AST:
    try:
        return ast.parse(src, filename=path)
    except SyntaxError as e:
        raise PythonParseError(_format_syntax_error(path, src, e)) from None


def changed_lines(repo: str = ".", base_ref: str = "HEAD~1", head_ref: str = "HEAD") -> Dict[str, Set[int]]:
    """Extract changed line numbers from git diff. For PRs use base_ref/head_ref (e.g. base_sha, head_sha)."""
    diff = subprocess.check_output(
        ["git", "-C", repo, "diff", "--unified=0", "--no-color", f"{base_ref}...{head_ref}"]
    ).decode()
    current = None
    changes: Dict[str, Set[int]] = {}
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            current = line[6:]
        elif line.startswith("@@") and current:
            parts = [p for p in line.split() if p.startswith("+")]
            if not parts:
                continue
            hunk = parts[0]
            start = int(hunk.split(",")[0][1:])
            count = int(hunk.split(",")[1]) if "," in hunk else 1
            changes.setdefault(current, set()).update(range(start, start + count))
    return changes

def symbols_containing_lines(path: str, lines: Set[int]) -> List[Tuple[str,int,int]]:
    """Find functions/classes that contain the given line numbers."""
    src = pathlib.Path(path).read_text(encoding="utf-8")
    tree = parse_python(path, src)
    out = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            start, end = node.lineno, getattr(node, "end_lineno", node.lineno)
            if any(start <= ln <= end for ln in lines):
                out.append((node.name, start, end))
    return out

def symbols_with_signature_changes(path: str, lines: Set[int]) -> Set[str]:
    """Find functions/classes whose SIGNATURES were changed (def line itself changed)."""
    src = pathlib.Path(path).read_text(encoding="utf-8")
    tree = parse_python(path, src)
    changed_signatures = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            # Check if the definition line itself was changed
            if node.lineno in lines:
                changed_signatures.add(node.name)
            # For classes, also check if __init__ signature changed
            if isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == "__init__":
                        if item.lineno in lines:
                            changed_signatures.add(node.name)
    return changed_signatures

def calls_in_lines(path: str, lines: Set[int]) -> Set[str]:
    """Extract function/class calls that occur within the specified line numbers."""
    src = pathlib.Path(path).read_text(encoding="utf-8")
    tree = parse_python(path, src)

    calls = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            # Check if this call is within the changed lines
            if hasattr(node, 'lineno') and node.lineno in lines:
                calls.add(node.func.id)
    return calls

def callgraph_for_files(files: List[str]) -> dict:
    """Build a simple call graph: which files define/call which symbols."""
    graph = {"calls": {}, "defs": {}}
    for f in files:
        src = pathlib.Path(f).read_text(encoding="utf-8")
        tree = parse_python(f, src)
        defs = {n.name for n in ast.walk(tree)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
        calls = {n.func.id for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        graph["defs"][f] = sorted(defs)
        graph["calls"][f] = sorted(calls)
    return graph

def one_hop_slice(changed_symbols: List[Tuple[str,str,int,int]], cg: dict) -> List[str]:
    """Find files that call or are called by the changed symbols."""
    target_names = {name for _, name, _, _ in changed_symbols}
    changed_files = {f for f, _, _, _ in changed_symbols}
    slice_files = set()

    # Callers: files that call the changed symbols
    for f, calls in cg["calls"].items():
        if f not in changed_files and any(t in calls for t in target_names):
            slice_files.add(f)

    # Callees: files defining what the changed files call
    calls_from_changed = set()
    for f in changed_files:
        calls_from_changed.update(cg["calls"].get(f, []))

    for f, defs in cg["defs"].items():
        if any(call in defs for call in calls_from_changed):
            slice_files.add(f)

    return sorted(slice_files)

def snippet(path: str, line: int, pad: int = 5) -> str:
    """Extract code snippet around a line number."""
    try:
        rows = pathlib.Path(path).read_text(encoding="utf-8").splitlines()
        i, j = max(0, line - pad - 1), min(len(rows), line + pad)
        return "\n".join(f"{k+1:>4}  {rows[k]}" for k in range(i, j))
    except Exception:
        return ""

def group_consecutive_lines(lines: List[int], gap: int = 5) -> List[List[int]]:
    """Group consecutive lines into chunks (within 'gap' lines of each other)."""
    if not lines:
        return []
    sorted_lines = sorted(lines)
    chunks = [[sorted_lines[0]]]
    for ln in sorted_lines[1:]:
        if ln - chunks[-1][-1] <= gap:
            chunks[-1].append(ln)
        else:
            chunks.append([ln])
    return chunks

def format_context_as_markdown(changes, changed_snippets, impact_snippets, diff_text) -> str:
    """Format the review context as structured markdown with XML-style tags."""
    lines = ["# Code Review Context\n"]

    # Section 1: Git Diff
    lines.append("## 1. Git Diff (What Changed)\n")
    lines.append("<diff>")
    lines.append(diff_text)
    lines.append("</diff>\n")

    # Section 2: Changed Code Snippets
    lines.append("## 2. Changed Code (Modified Files with Context)\n")
    for item in changed_snippets:
        lines.append(f'<file name="{item["file"]}" lines="{item["lines"]}" type="changed">')
        lines.append("```python")
        lines.append(item["text"])
        lines.append("```")
        lines.append("</file>\n")

    # Section 3: Impact Code (both directions)
    lines.append("## 3. Impact Code (Contracts & Call Sites)\n")

    # Separate callees and callers
    callees = [item for item in impact_snippets if item.get("role") == "callee"]
    callers = [item for item in impact_snippets if item.get("role") == "caller"]

    # CALLEES section
    lines.append("### CALLEES: Definitions that the changed code CALLS (check if changed code respects these contracts)")
    lines.append("<callees>")
    if callees:
        for item in callees:
            lines.append(f'<file name="{item["file"]}" symbol="{item["symbol"]}">')
            lines.append("```python")
            lines.append(item["text"])
            lines.append("```")
            lines.append("</file>")
    else:
        lines.append("None")
    lines.append("</callees>\n")

    # CALLERS section
    lines.append("### CALLERS: Call sites that invoke the changed functions/classes (check if callers pass correct arguments)")
    lines.append("<callers>")
    if callers:
        for item in callers:
            lines.append(f'<file name="{item["file"]}" symbol="{item["symbol"]}">')
            lines.append("```python")
            lines.append(item["text"])
            lines.append("```")
            lines.append("</file>")
    else:
        lines.append("None")
    lines.append("</callers>\n")

    return "\n".join(lines)


def build_review_context(
    repo: str = ".",
    base_ref: str = "HEAD~1",
    head_ref: str = "HEAD",
) -> str:
    """Build the context packet for LLM review. Expects cwd to be the repo when repo is '.'."""
    changes = changed_lines(repo, base_ref, head_ref)
    changed_symbols = []
    for f, lines in changes.items():
        if f.endswith(".py") and pathlib.Path(f).exists():
            for name, start, end in symbols_containing_lines(f, lines):
                changed_symbols.append((f, name, start, end))

    all_py_files = pathlib.Path(repo).rglob("*.py")
    excluded = {'.venv', 'venv', 'env', '.tox', 'site-packages', 'node_modules', '__pycache__'}
    repo_files = [str(p) for p in all_py_files if not any(part in p.parts for part in excluded)]

    cg = callgraph_for_files(repo_files)
    impact_files = set(one_hop_slice(changed_symbols, cg))

    # Full git diff
    diff_text = subprocess.check_output(
        ["git", "-C", repo, "diff", "--unified=3", "--no-color", f"{base_ref}...{head_ref}"]
    ).decode()

    # Snippets of changed code (grouped by proximity)
    changed_snippets = []
    for f, lines in changes.items():
        if not lines:
            continue
        for chunk in group_consecutive_lines(list(lines)):
            center = chunk[len(chunk) // 2]
            changed_snippets.append({
                "file": f,
                "lines": f"{chunk[0]}-{chunk[-1]}",
                "text": snippet(f, center, pad=8)
            })

    # Track shown lines to avoid duplication
    shown_lines = {}
    for item in changed_snippets:
        f = item["file"]
        if "-" in item["lines"]:
            start, end = map(int, item["lines"].split("-"))
            shown_lines.setdefault(f, set()).update(range(start, end + 1))

    # Snippets from impact files:
    # 1. CALLEES - definitions that changed lines actually call
    calls_from_changed = set()
    for f, lines in changes.items():
        if f.endswith(".py") and pathlib.Path(f).exists():
            calls_from_changed.update(calls_in_lines(f, lines))

    # 2. CALLERS - collect names of functions/classes whose SIGNATURES were changed
    # (not just any function that contains a change)
    changed_signature_names = set()
    for f, lines in changes.items():
        if f.endswith(".py") and pathlib.Path(f).exists():
            changed_signature_names.update(symbols_with_signature_changes(f, lines))

    impact_snippets = []
    for f in sorted(impact_files):
        src = pathlib.Path(f).read_text(encoding="utf-8")
        tree = parse_python(f, src)

        # Show CALLEES: definitions that changed code calls
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name in calls_from_changed:
                init_line = node.lineno
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == "__init__":
                        init_line = item.lineno
                        break
                snippet_range = range(max(1, init_line - 12), init_line + 13)
                if f in shown_lines and any(ln in shown_lines[f] for ln in snippet_range):
                    continue
                impact_snippets.append({
                    "file": f,
                    "symbol": node.name,
                    "role": "callee",
                    "text": snippet(f, init_line, pad=12)
                })
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in calls_from_changed:
                snippet_range = range(max(1, node.lineno - 10), node.lineno + 11)
                if f in shown_lines and any(ln in shown_lines[f] for ln in snippet_range):
                    continue
                impact_snippets.append({
                    "file": f,
                    "symbol": node.name,
                    "role": "callee",
                    "text": snippet(f, node.lineno, pad=10)
                })

        # Show CALLERS: code that calls functions/classes whose SIGNATURES changed
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id in changed_signature_names:
                    if hasattr(node, 'lineno'):
                        snippet_range = range(max(1, node.lineno - 8), node.lineno + 9)
                        if f in shown_lines and any(ln in shown_lines[f] for ln in snippet_range):
                            continue
                        impact_snippets.append({
                            "file": f,
                            "symbol": f"call to {node.func.id}",
                            "role": "caller",
                            "text": snippet(f, node.lineno, pad=8)
                        })

    return format_context_as_markdown(changes, changed_snippets, impact_snippets, diff_text)
