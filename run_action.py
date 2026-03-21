#!/usr/bin/env python3
# run_action.py - GitHub Action entry point. Runs review and posts PR comment.

import os
import sys
import json


def main() -> int:
    base_ref = os.environ.get("GITHUB_BASE_REF") or os.environ.get("INPUT_BASE_REF", "HEAD~1")
    head_ref = os.environ.get("GITHUB_HEAD_REF") or os.environ.get("INPUT_HEAD_REF", "HEAD")
    repo = os.environ.get("GITHUB_WORKSPACE", ".")
    provider = os.environ.get("INPUT_PROVIDER", "openai").lower()

    api_key = ""
    if provider == "openai":
        api_key = os.environ.get("INPUT_OPENAI_API_KEY", "") or os.environ.get("OPENAI_API_KEY", "")
    elif provider == "anthropic":
        api_key = os.environ.get("INPUT_ANTHROPIC_API_KEY", "") or os.environ.get("ANTHROPIC_API_KEY", "")
    elif provider == "google":
        api_key = os.environ.get("INPUT_GOOGLE_API_KEY", "") or os.environ.get("GOOGLE_API_KEY", "")

    if not api_key:
        print(f"::error::Missing API key for provider '{provider}'. Set INPUT_{provider.upper()}_API_KEY or add the secret to your workflow.")
        return 1

    # PR context: use base/head SHAs when in a PR
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if event_path:
        try:
            with open(event_path) as f:
                event = json.load(f)
            pr = event.get("pull_request")
            if pr:
                base_ref = pr.get("base", {}).get("sha", base_ref)
                head_ref = pr.get("head", {}).get("sha", head_ref)
        except Exception:
            pass

    os.chdir(repo)

    # Ensure action's Python modules are importable
    action_path = os.environ.get("GITHUB_ACTION_PATH", os.path.dirname(os.path.abspath(__file__)))
    if action_path not in sys.path:
        sys.path.insert(0, action_path)

    from review_demo import build_review_context
    from llm_providers import run_llm_provider

    context = build_review_context(repo=".", base_ref=base_ref, head_ref=head_ref)
    result = run_llm_provider(provider, context, api_key, model=os.environ.get("INPUT_MODEL"))

    bugs = result.get("bugs", [])
    body = _format_comment(bugs)

    token = os.environ.get("GITHUB_TOKEN")
    repo_full_name = os.environ.get("GITHUB_REPOSITORY", "")
    if token and event_path and repo_full_name:
        try:
            with open(event_path) as f:
                event = json.load(f)
            pr = event.get("pull_request")
            if pr:
                _post_comment(token, pr["number"], body, repo_full_name)
        except Exception as e:
            print(f"::warning::Could not post PR comment: {e}")
    else:
        print(body)

    return 0


def _format_comment(bugs: list) -> str:
    if not bugs:
        return "## Dexter Reviews\n\nNo bugs found."

    lines = ["## Dexter Reviews\n"]
    for i, b in enumerate(bugs, 1):
        cat = b.get("bug_category", "")
        file_ = b.get("changed_file", "")
        ln = b.get("changed_lines", "")
        summary = b.get("summary", "")
        comment = b.get("comment", "")
        fix = b.get("diff_fix_suggestion", "").strip()
        lines.append(f"### {i}. {summary}")
        lines.append(f"- **File:** `{file_}` (lines {ln})")
        lines.append(f"- **Category:** {cat}")
        lines.append(f"- **Details:** {comment}")
        if fix:
            lines.append(f"```diff\n{fix}\n```")
        lines.append("")
    return "\n".join(lines)


def _post_comment(token: str, pr_number: int, body: str, repo_full_name: str) -> None:
    import urllib.request

    owner, repo_name = repo_full_name.split("/", 1)
    url = f"https://api.github.com/repos/{owner}/{repo_name}/issues/{pr_number}/comments"
    data = json.dumps({"body": body}).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github.v3+json")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as resp:
        if resp.status not in (200, 201):
            raise RuntimeError(f"GitHub API error: {resp.status}")


if __name__ == "__main__":
    sys.exit(main())
