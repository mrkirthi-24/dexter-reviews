# demo_review.py
# CLI for smart-mode code review (impact slicing)

import os
import sys
import argparse

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from review_demo import build_review_context, run_llm


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Smart-mode code review (impact slicing: diff + callers/callees)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Example: python demo_review.py -r ./my-repo"
    )
    parser.add_argument("-r", "--repo", required=True, help="Path to the git repository to review")
    parser.add_argument("--show-context", action="store_true", help="Print context only, skip LLM call")
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
        run_llm(context)
    finally:
        os.chdir(original_dir)


if __name__ == "__main__":
    main()
