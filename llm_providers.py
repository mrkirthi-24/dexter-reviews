# llm_providers.py
# Multi-provider LLM adapter for code review. Same prompt/schema across OpenAI, Anthropic, Google.

import json
import re
from typing import Any


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

Focus on real bugs, not style. If nothing critical is found, return an empty bugs array. For diff_fix_suggestion, provide a unified diff format if you have a concrete fix, or empty string if not.

Respond with ONLY valid JSON matching this schema, no other text:
{"bugs":[{"changed_file":"string","changed_lines":"string","bug_category":"contract-mismatch|logic-error|concurrency|resource-management|error-handling|security","summary":"string","comment":"string","diff_fix_suggestion":"string"}]}

Review the following context:

"""


def _parse_json_response(text: str) -> dict:
    """Extract and parse JSON from LLM response (handles markdown code blocks)."""
    text = text.strip()
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if match:
        text = match.group(1).strip()
    return json.loads(text)


def run_openai(review_context: str, api_key: str, model: str = "gpt-4o-mini") -> dict:
    """Run review via OpenAI."""
    from openai import OpenAI
    from openai.types.responses import ResponseOutputMessage, ResponseOutputText

    client = OpenAI(api_key=api_key)
    json_schema = {
        "type": "object",
        "properties": {
            "bugs": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "changed_file": {"type": "string"},
                        "changed_lines": {"type": "string"},
                        "bug_category": {"type": "string", "enum": ["contract-mismatch", "logic-error", "concurrency", "resource-management", "error-handling", "security"]},
                        "summary": {"type": "string"},
                        "comment": {"type": "string"},
                        "diff_fix_suggestion": {"type": "string"},
                    },
                    "required": ["changed_file", "changed_lines", "bug_category", "summary", "comment", "diff_fix_suggestion"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["bugs"],
        "additionalProperties": False,
    }

    response = client.responses.create(
        model=model,
        input=PROMPT_PREFIX + review_context,
        text={"format": {"type": "json_schema", "name": "bug_report", "schema": json_schema, "strict": True}},
    )
    output_text = ""
    for item in response.output:
        if isinstance(item, ResponseOutputMessage) and item.content:
            for c in item.content:
                if isinstance(c, ResponseOutputText):
                    output_text += c.text
    return json.loads(output_text)


def run_anthropic(review_context: str, api_key: str, model: str = "claude-sonnet-4-20250514") -> dict:
    """Run review via Anthropic Claude."""
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model=model,
        max_tokens=4096,
        messages=[{"role": "user", "content": PROMPT_PREFIX + review_context}],
    )
    text = msg.content[0].text if msg.content else ""
    return _parse_json_response(text)


def run_google(review_context: str, api_key: str, model: str = "gemini-2.0-flash") -> dict:
    """Run review via Google Gemini."""
    import google.generativeai as genai

    genai.configure(api_key=api_key)
    m = genai.GenerativeModel(model)
    response = m.generate_content(
        PROMPT_PREFIX + review_context,
        generation_config=genai.types.GenerationConfig(
            response_mime_type="application/json",
            temperature=0,
        ),
    )
    return _parse_json_response(response.text)


def run_llm_provider(provider: str, review_context: str, api_key: str, model: str | None = None) -> dict:
    """Dispatch to the appropriate LLM provider. Returns parsed bugs dict."""
    providers = {
        "openai": (run_openai, "gpt-4o-mini"),
        "anthropic": (run_anthropic, "claude-sonnet-4-20250514"),
        "google": (run_google, "gemini-2.0-flash"),
    }
    if provider not in providers:
        raise ValueError(f"Unknown provider: {provider}. Use one of: {list(providers.keys())}")
    fn, default_model = providers[provider]
    return fn(review_context, api_key, model or default_model)
