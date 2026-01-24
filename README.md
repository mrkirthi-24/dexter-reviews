# AI Code Reviewer - Outside-Diff Impact Slicing Demo

An AI-powered code review tool that demonstrates **Outside-Diff Impact Slicing** - a technique that finds bugs by analyzing the boundaries between changed code and its callers/callees.

## The Problem

Traditional AI code reviews only look at the diff. This misses bugs that occur at the **boundaries** between changed code and unchanged code - like when a function signature changes but callers aren't updated.

## The Solution

This tool demonstrates three approaches to AI code review:

| Mode | What it sends to LLM | Result |
|------|---------------------|--------|
| `diff-only` | Just the git diff | Often misses bugs (no context) |
| `all-code` | Entire codebase | Finds bugs but uses many tokens |
| `smart` | Diff + callers/callees | Finds bugs with minimal tokens |

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Set up your API key

Create a `.env` file:
```
OPENAI_API_KEY=sk-your-key-here
```

### 3. Run the comparison demo

```bash
python demo_review.py -r ./demo_project --compare
```

This runs all three modes and shows a comparison table:

```
Mode         Bug Found?   Input Tokens   Time (s)  
--------------------------------------------------
diff-only    Yes          390            4.85      
all-code     Yes          10,586         5.60      
smart        Yes          1,041          2.60      
--------------------------------------------------

SUMMARY:
  - Smart mode uses 90.2% fewer tokens than all-code mode
```

## CLI Usage

```bash
# Run a single mode
python demo_review.py -r /path/to/repo -m diff-only
python demo_review.py -r /path/to/repo -m all-code
python demo_review.py -r /path/to/repo -m smart

# Compare all three modes
python demo_review.py -r /path/to/repo --compare

# Show the context being sent to the LLM
python demo_review.py -r /path/to/repo -m smart --show-context
```

### Options

| Flag | Description |
|------|-------------|
| `-r, --repo` | Path to the git repository to review (required) |
| `-m, --mode` | Review mode: `diff-only`, `all-code`, or `smart` |
| `--compare` | Run all three modes and show comparison |
| `--show-context` | Print the full context being sent to the LLM |

## Demo Project

The `demo_project/` folder contains a sample e-commerce application with an intentional bug:

- `calculator.py` - Has a function `calculate_discount(price, discount_percent, min_purchase)` with 3 parameters
- `order.py` - Calls `calculate_discount(subtotal, discount_percent)` with only 2 parameters

This simulates a real-world scenario where a function signature was changed but not all callers were updated.

## How It Works

### Smart Mode (Impact Slicing)

1. **Parse the diff** - Extract which lines changed in which files
2. **Find changed symbols** - Identify functions/classes containing changes
3. **Build call graph** - Map which files call which functions
4. **One-hop slice** - Find callers (who calls the changed code) and callees (what the changed code calls)
5. **Format context** - Structure the diff, changed code, and impact code as markdown
6. **Send to LLM** - GPT analyzes the context and reports bugs

```
git diff → changed_lines → symbols_containing_lines → callgraph → one_hop_slice
                                                                        ↓
                                                              impact files (callers/callees)
                                                                        ↓
                                                              format_context_as_markdown
                                                                        ↓
                                                                    run_llm
```

## Files

| File | Description |
|------|-------------|
| `demo_review.py` | CLI tool for comparing review approaches |
| `review_demo.py` | Core implementation of impact slicing |
| `demo_project/` | Sample e-commerce project with intentional bug |
| `requirements.txt` | Python dependencies |

## Requirements

- Python 3.10+
- Git repository with at least one commit
- OpenAI API key

## Limitations

- Currently supports Python codebases only
- Works best on focused PRs (10-50 changed lines)
- Large codebases may hit token limits in all-code mode
