# demo_review.py
# CLI for smart-mode code review (impact slicing)

import os
import sys
import json
import argparse

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from llm_providers import print_review_statistics, run_llm_provider
from dexter_rules import load_project_rules
from dexter_thinks import build_review_context


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Smart-mode code review (impact slicing: diff + callers/callees)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Example: python dexter_cli.py -r ./my-repo"
    )
    parser.add_argument("--model", default=None, help="Optional model override")
    parser.add_argument("-r", "--repo", required=True, help="Path to the git repository to review")
    parser.add_argument("--show-context", action="store_true", help="Print context only, skip LLM call")
    parser.add_argument("--provider", default="openai", choices=["openai", "anthropic", "google"], help="LLM provider")
    args = parser.parse_args()

    repo_path = os.path.abspath(args.repo)
    if not os.path.isdir(repo_path):
        print(f"Error: Repository path does not exist: {repo_path}")
        sys.exit(1)
    if not os.path.isdir(os.path.join(repo_path, ".git")):
        print(f"Error: Not a git repository: {repo_path}")
        sys.exit(1)

    original_dir = os.getcwd()
    os.chdir(repo_path)
    try:
        print("Building review context (smart mode)…")
        context = build_review_context(".")
        print(context)

        if args.show_context:
            return

        print("\n" + "="*80)
        print("Calling the model…")
        print("="*80 + "\n")
        provider = args.provider.lower()
        env_key_name = f"{provider.upper()}_API_KEY"
        api_key = os.environ.get(env_key_name, "")
        if not api_key:
            print(f"Error: Missing API key in environment variable {env_key_name}")
            sys.exit(1)
        rules, rules_warning = load_project_rules(".")
        if rules_warning:
            print(f"Warning: {rules_warning}")
        result, elapsed, usage = run_llm_provider(
            provider, context, api_key, model=args.model, project_rules=rules
        )
        print(json.dumps(result, indent=2))
        print_review_statistics(elapsed, usage, result)
    finally:
        os.chdir(original_dir)


if __name__ == "__main__":
    main()
