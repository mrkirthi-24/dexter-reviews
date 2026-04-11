# Dexter Reviews

AI code review via **Impact Slicing** — diff + callers/callees for bug detection with minimal tokens. Supports OpenAI, Anthropic Claude, and Google Gemini.

## GitHub Action

Add to your repo's `.github/workflows/dexter-review.yml`:

```yaml
name: Dexter Review
on:
  pull_request:
    branches: [main, master]
jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: YOUR_ORG/dexter-reviews@main
        with:
          provider: openai
          openai_api_key: ${{ secrets.OPENAI_API_KEY }}
```

**Provider options:** `openai` | `anthropic` | `google`

**Required secrets** (add one for your chosen provider):
- `OPENAI_API_KEY` — OpenAI
- `ANTHROPIC_API_KEY` — Anthropic Claude
- `GOOGLE_API_KEY` — Google Gemini

## CLI (Local)

```bash
pip install -r requirements.txt
# Set OPENAI_API_KEY in .env
python dexter-cli.py -r ./your-repo
```

| Flag             | Description                    |
| ---------------- | ------------------------------ |
| `-r, --repo`     | Path to git repo (required)    |
| `--show-context` | Print context only, no LLM     |
| `--provider`     | `openai`, `anthropic`, `google`|
| `--model`        | Optional model override        |

## Project-Specific Rules

Dexter can load repository-specific review rules from:

`/.github/workflows/DEXTER_RULES.md`

If this file exists, its content is injected into the review prompt and violations can be reported as `project-rule`.

## How It Works

1. Parse diff → changed lines → symbols → call graph → one-hop slice
2. Format diff + changed code + callers/callees as markdown
3. Send to LLM; comment results on the PR

## Requirements

- Python 3.10+
- Git repo with ≥1 commit
- One of: OpenAI, Anthropic, or Google API key

## Limitations

- Python codebases only
- Best for focused PRs (10–50 changed lines)
