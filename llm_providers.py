# llm_providers.py
# Multi-provider LLM adapter for code review. Same prompt/schema across OpenAI, Anthropic, Google.

import json
import re
import time
from collections import Counter
from enum import StrEnum
from typing import Any

# OpenAI / Anthropic / Gemini usage objects use different field names; try in provider-priority order.
_USAGE_INPUT_ATTRS = ("input_tokens", "prompt_tokens", "prompt_token_count")
_USAGE_OUTPUT_ATTRS = ("output_tokens", "completion_tokens", "candidates_token_count")
_USAGE_TOTAL_ATTRS = ("total_tokens", "total_token_count")


def _first_usage_attr(usage: Any, attr_names: tuple[str, ...]) -> Any:
    for name in attr_names:
        v = getattr(usage, name, None)
        if v is not None:
            return v
    return None


def print_review_statistics(elapsed_time: float, usage: Any | None, result: dict | None = None) -> None:
    """Print LLM usage and optional bug counts after the review output."""
    print("\n" + "=" * 80)
    print("STATISTICS")
    print("=" * 80)
    print(f"Time taken: {elapsed_time:.2f} seconds")
    if usage is None:
        print("Input tokens: N/A")
        print("Output tokens: N/A")
    else:
        in_tok = _first_usage_attr(usage, _USAGE_INPUT_ATTRS)
        out_tok = _first_usage_attr(usage, _USAGE_OUTPUT_ATTRS)
        print(f"Input tokens: {in_tok if in_tok is not None else 'N/A'}")
        print(f"Output tokens: {out_tok if out_tok is not None else 'N/A'}")
        total = _first_usage_attr(usage, _USAGE_TOTAL_ATTRS)
        if total is not None:
            print(f"Total tokens: {total}")
    if result is not None:
        bugs = result.get("bugs") or []
        print(f"Bugs reported: {len(bugs)}")
        if bugs:
            cats = Counter(b.get("bug_category", "unknown") for b in bugs)
            for cat, n in sorted(cats.items(), key=lambda x: (-x[1], x[0])):
                print(f"  {cat}: {n}")


class OpenAIModel(StrEnum):
    GPT_4O = "gpt-4o"

class AnthropicModel(StrEnum):
    SONNET_4_6 = "claude-sonnet-4-6"

class GoogleModel(StrEnum):
    GEMINI_3_1_PRO_PREVIEW = "gemini-3.1-pro-preview"

BUG_CATEGORIES = [
    "contract-mismatch",
    "logic-error",
    "concurrency",
    "resource-management",
    "error-handling",
    "security",
    "project-rule",
]


PROMPT_PREFIX = """You are a senior code reviewer analyzing a PR for bugs. You will receive structured markdown with THREE sections:

1. Git Diff: Shows what changed (in <diff> tags)
2. Changed Code: Snippets from modified files (in <file type="changed"> tags)
3. Impact Code: Both CALLEES (definitions the changed code calls) and CALLERS (code that calls the changed symbols). These show contracts/signatures and usage patterns.

YOUR TASK: Find real bugs in the CHANGED CODE (type="changed" files). Look for:
- CONTRACT MISMATCHES: Wrong number of parameters, missing arguments, signature changes where callers weren't updated
- LOGIC ERRORS: Off-by-one errors, incorrect conditionals, wrong operators, missing edge case handling
- CONCURRENCY ISSUES: Race conditions, deadlocks, missing synchronization, unsafe shared state access
- RESOURCE MANAGEMENT: Leaks, missing cleanup, incorrect resource lifetimes
- ERROR HANDLING: Unhandled exceptions, incorrect error propagation, silent failures
- SECURITY: Injection vulnerabilities, missing validation, unsafe operations

CRITICAL: Your findings MUST reference the CHANGED files (type="changed"), NOT the impact files. Report the specific line number in the CHANGED file where the bug occurs.

EVIDENCE RULES — these prevent false positives and hallucination. Follow them strictly:
- Report a bug ONLY if you can point to the specific evidence in the provided context that proves it. Put that proof in the "evidence" field (quote the exact line(s) from the diff, changed code, CALLEES, or CALLERS).
- DO NOT GUESS SIGNATURES YOU CANNOT SEE. For contract-mismatch / wrong-argument findings, the callee's definition MUST appear in the CALLEES section. If the called function/class is from an external library or is otherwise NOT shown in CALLEES, you do not know its real signature — DO NOT flag it. Assume the existing call works.
- Do not infer the behavior of code that is not shown. Absence of context is NOT evidence of a bug.
- Prefer false negatives over false positives. A wrong flag costs the team more than a missed nit. When unsure, lower the confidence or omit the finding.

CONFIDENCE — set "confidence" honestly:
- "high": evidence in context directly proves the bug; a competent engineer would agree it must be fixed.
- "medium": strong signal but depends on an assumption you cannot fully verify from the context.
- "low": speculative or style-level. (Low-confidence findings are filtered out before posting, so only include one if you genuinely believe it.)

SEVERITY — set "severity": "critical" (crash, data loss, security hole, broken contract), "major" (wrong result in a real path), or "minor" (edge case, hygiene).

Focus on real bugs. If project rules are provided, enforce them as hard requirements and use "project-rule" when applicable. If you find no bug you can prove from the provided context, return an empty bugs array — that is a valid and good result. For diff_fix_suggestion, provide a unified diff format ONLY if you have a concrete, correct fix that you can verify against the shown context; otherwise empty string.

Respond with ONLY valid JSON matching this schema, no other text:
{"bugs":[{"changed_file":"string","changed_lines":"string","bug_category":"contract-mismatch|logic-error|concurrency|resource-management|error-handling|security|project-rule","severity":"critical|major|minor","confidence":"high|medium|low","summary":"string","comment":"string","evidence":"string","diff_fix_suggestion":"string"}]}
"""


def _parse_json_response(text: str) -> dict:
    """Extract and parse JSON from LLM response.

    Tolerates markdown code fences and surrounding prose by falling back to
    the substring between the first ``{`` and the last ``}``.
    """
    if not text or not text.strip():
        raise ValueError("LLM returned empty response; expected JSON.")
    stripped = text.strip()

    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", stripped)
    if fence:
        stripped = fence.group(1).strip()

    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(stripped[start : end + 1])
            except json.JSONDecodeError:
                pass
        snippet = text[:500].replace("\n", "\\n")
        raise ValueError(
            f"LLM response was not valid JSON. First 500 chars: {snippet!r}"
        )


def build_prompt(review_context: str, project_rules: str | None = None) -> str:
    prompt = PROMPT_PREFIX
    if project_rules:
        prompt += (
            "\n\n## Project rules (repository-specific)\n\n"
            "The following rules were read from DEXTER_RULES.md. "
            "Apply them in addition to the bug-finding task above. "
            "When a finding is primarily a rule violation, set bug_category to project-rule.\n\n"
            "<rules>\n"
            f"{project_rules}\n"
            "</rules>\n"
        )
    prompt += "\n\nReview the following context:\n\n"
    prompt += review_context
    return prompt


def _json_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "bugs": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "changed_file": {"type": "string"},
                        "changed_lines": {"type": "string"},
                        "bug_category": {"type": "string", "enum": BUG_CATEGORIES},
                        "severity": {"type": "string", "enum": ["critical", "major", "minor"]},
                        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                        "summary": {"type": "string"},
                        "comment": {"type": "string"},
                        "evidence": {"type": "string"},
                        "diff_fix_suggestion": {"type": "string"},
                    },
                    "required": ["changed_file", "changed_lines", "bug_category", "severity", "confidence", "summary", "comment", "evidence", "diff_fix_suggestion"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["bugs"],
        "additionalProperties": False,
    }


def run_openai(review_context: str, api_key: str, model: str = OpenAIModel.GPT_4O, project_rules: str | None = None) -> tuple[dict, float, Any]:
    """Run review via OpenAI. Returns (parsed bugs dict, elapsed seconds, usage object)."""
    from openai import OpenAI
    from openai.types.responses import ResponseOutputMessage, ResponseOutputText

    from openai import BadRequestError

    client = OpenAI(api_key=api_key)
    request_kwargs = {
        "model": model,
        "input": build_prompt(review_context, project_rules),
        "temperature": 0,
        "text": {"format": {"type": "json_schema", "name": "bug_report", "schema": _json_schema(), "strict": True}},
    }
    t0 = time.perf_counter()
    try:
        response = client.responses.create(**request_kwargs)
    except BadRequestError as e:
        # Reasoning models (e.g. gpt-5.x) reject `temperature`. Retry once without it.
        if e.param == "temperature" or "temperature" in str(e):
            request_kwargs.pop("temperature", None)
            print(f"Model '{model}' rejected temperature; retrying without it.")
            response = client.responses.create(**request_kwargs)
        else:
            raise
    elapsed = time.perf_counter() - t0
    usage = getattr(response, "usage", None)
    output_text = ""
    for item in response.output:
        if isinstance(item, ResponseOutputMessage) and item.content:
            for c in item.content:
                if isinstance(c, ResponseOutputText):
                    output_text += c.text
    return json.loads(output_text), elapsed, usage


def run_anthropic(review_context: str, api_key: str, model: str = AnthropicModel.SONNET_4_6, project_rules: str | None = None) -> tuple[dict, float, Any]:
    """Run review via Anthropic Claude. Returns (parsed bugs dict, elapsed seconds, usage object)."""
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    tool = {
        "name": "report_bugs",
        "description": "Report the bugs found in the changed code.",
        "input_schema": _json_schema(),
    }
    t0 = time.perf_counter()
    msg = client.messages.create(
        model=model,
        max_tokens=8192,
        temperature=0,
        tools=[tool],
        tool_choice={"type": "tool", "name": "report_bugs"},
        messages=[
            {"role": "user", "content": build_prompt(review_context, project_rules)},
        ],
    )
    elapsed = time.perf_counter() - t0
    usage = getattr(msg, "usage", None)
    for block in msg.content or []:
        if getattr(block, "type", None) == "tool_use" and block.name == "report_bugs":
            return block.input, elapsed, usage
    raise ValueError("Anthropic response did not include the expected report_bugs tool call.")


def run_google(review_context: str, api_key: str, model: str = GoogleModel.GEMINI_3_1_PRO_PREVIEW, project_rules: str | None = None) -> tuple[dict, float, Any]:
    """Run review via Google Gemini. Returns (parsed bugs dict, elapsed seconds, usage object)."""
    import google.generativeai as genai

    genai.configure(api_key=api_key)
    m = genai.GenerativeModel(model)
    t0 = time.perf_counter()
    response = m.generate_content(
        build_prompt(review_context, project_rules),
        generation_config=genai.types.GenerationConfig(
            response_mime_type="application/json",
            temperature=0,
        ),
    )
    elapsed = time.perf_counter() - t0
    usage = getattr(response, "usage_metadata", None)
    return _parse_json_response(response.text), elapsed, usage


def run_llm_provider(
    provider: str,
    review_context: str,
    api_key: str,
    model: str | None = None,
    project_rules: str | None = None,
) -> tuple[dict, float, Any]:
    """Dispatch to the appropriate LLM provider. Returns (parsed bugs dict, elapsed seconds, usage object)."""
    providers = {
        "openai": (run_openai, OpenAIModel.GPT_4O),
        "anthropic": (run_anthropic, AnthropicModel.SONNET_4_6),
        "google": (run_google, GoogleModel.GEMINI_3_1_PRO_PREVIEW),
    }
    if provider not in providers:
        raise ValueError(f"Unknown provider: {provider}. Use one of: {list(providers.keys())}")
    fn, default_model = providers[provider]
    return fn(review_context, api_key, model or default_model, project_rules=project_rules)
