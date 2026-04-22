#!/usr/bin/env python3
"""
Daily Research Digest — Multi-Agent Debate in LLMs
Runs via GitHub Actions at 8:00 AM Vietnam time (01:00 UTC).

Required secret in GitHub repo settings:
    ANTHROPIC_API_KEY — https://console.anthropic.com/settings/keys
"""

import glob
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import anthropic
import requests
from bs4 import BeautifulSoup

try:
    from duckduckgo_search import DDGS
    _DDGS_AVAILABLE = True
except ImportError:
    _DDGS_AVAILABLE = False
    print("[WARN] duckduckgo_search not available — web_search will return empty results")

# ── Paths ──────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parent.parent

# ── Date (Vietnam timezone UTC+7) ─────────────────────────────────────────
VN_TZ = timezone(timedelta(hours=7))
NOW_VN = datetime.now(VN_TZ)
RUN_DATE = NOW_VN.strftime("%Y-%m-%d")
RUN_DATE_HUMAN = NOW_VN.strftime("%d/%m/%Y")

# ── Pre-flight checks ──────────────────────────────────────────────────────
_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
if not _API_KEY:
    print("ERROR: ANTHROPIC_API_KEY is not set or empty.")
    print("  → Go to: https://github.com/haudung23/Agent_focus/settings/secrets/actions")
    print("  → Add secret: ANTHROPIC_API_KEY = <your key from console.anthropic.com>")
    raise SystemExit(1)

_prompt_file = REPO_ROOT / "prompts" / "daily_digest_prompt.md"
if not _prompt_file.exists():
    print(f"ERROR: Prompt file not found at {_prompt_file}")
    raise SystemExit(1)


# ═══════════════════════════════════════════════════════════════════════════
# Tool implementations
# ═══════════════════════════════════════════════════════════════════════════

def tool_web_search(query: str, max_results: int = 10) -> str:
    """DuckDuckGo web search — no API key needed."""
    if not _DDGS_AVAILABLE:
        return "[web_search unavailable: duckduckgo_search not installed]"
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        if not results:
            return "[No results found]"
        lines = []
        for r in results:
            lines.append(f"Title: {r.get('title', 'N/A')}")
            lines.append(f"URL: {r.get('href', 'N/A')}")
            lines.append(f"Snippet: {r.get('body', 'N/A')}")
            lines.append("")
        return "\n".join(lines)
    except Exception as e:
        return f"[Search error: {e}]"


def tool_web_fetch(url: str) -> str:
    """Fetch and extract readable text from a URL."""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; ResearchBot/1.0)"}
        r = requests.get(url, headers=headers, timeout=30)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        return text[:12000]  # cap at 12k chars to stay within context
    except Exception as e:
        return f"[Fetch error for {url}: {e}]"


def _resolve(path: str) -> Path:
    return REPO_ROOT / path.lstrip("/\\")


def tool_read_file(path: str) -> str:
    p = _resolve(path)
    if not p.exists():
        return "[File not found]"
    return p.read_text(encoding="utf-8")


def tool_write_file(path: str, content: str) -> str:
    p = _resolve(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"[Written {len(content)} chars → {path}]"


def tool_append_to_file(path: str, content: str) -> str:
    p = _resolve(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(content)
    return f"[Appended {len(content)} chars → {path}]"


def tool_list_files(pattern: str) -> str:
    matches = glob.glob(str(REPO_ROOT / pattern))
    rel = sorted(str(Path(m).relative_to(REPO_ROOT)) for m in matches)
    return "\n".join(rel) if rel else "[No files matched]"


def tool_run_bash(command: str) -> str:
    cmd = command.strip()
    if not cmd.startswith("git "):
        return "[Blocked: only git commands allowed]"
    result = subprocess.run(
        cmd, shell=True, cwd=REPO_ROOT,
        capture_output=True, text=True, timeout=60,
    )
    return (result.stdout + result.stderr).strip() or "[No output]"


# ═══════════════════════════════════════════════════════════════════════════
# Claude tool schema
# ═══════════════════════════════════════════════════════════════════════════

TOOLS = [
    {
        "name": "web_search",
        "description": (
            "Search the web with DuckDuckGo. Use this for all 16 research queries "
            "(10 general + 6 academic sources). Returns titles, URLs, and snippets."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_results": {"type": "integer", "default": 10},
            },
            "required": ["query"],
        },
    },
    {
        "name": "web_fetch",
        "description": (
            "Fetch and extract readable text from a URL. Use for arXiv abstract pages, "
            "Semantic Scholar, OpenReview, ACL Anthology, Papers with Code, etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"url": {"type": "string", "description": "Full URL to fetch"}},
            "required": ["url"],
        },
    },
    {
        "name": "read_file",
        "description": "Read a file from the repository. Path is relative to repo root.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "e.g. 'links.txt'"}},
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Write (overwrite) a file in the repository root.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "append_to_file",
        "description": "Append content to a file (creates the file if it does not exist).",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "list_files",
        "description": "List files matching a glob pattern relative to repo root.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "e.g. 'noi_dung_*.md'"}
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "run_bash",
        "description": (
            "Run a git command in the repository (only git commands are allowed). "
            "Do NOT run git push — the CI pipeline handles that."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "e.g. 'git add links.txt'"}
            },
            "required": ["command"],
        },
    },
]

TOOL_HANDLERS = {
    "web_search":     lambda i: tool_web_search(i["query"], i.get("max_results", 10)),
    "web_fetch":      lambda i: tool_web_fetch(i["url"]),
    "read_file":      lambda i: tool_read_file(i["path"]),
    "write_file":     lambda i: tool_write_file(i["path"], i["content"]),
    "append_to_file": lambda i: tool_append_to_file(i["path"], i["content"]),
    "list_files":     lambda i: tool_list_files(i["pattern"]),
    "run_bash":       lambda i: tool_run_bash(i["command"]),
}


# ═══════════════════════════════════════════════════════════════════════════
# Agentic loop
# ═══════════════════════════════════════════════════════════════════════════

def run() -> None:
    # Initialize client and prompt inside run() so pre-flight checks run first
    client = anthropic.Anthropic(api_key=_API_KEY)

    original_prompt = _prompt_file.read_text(encoding="utf-8")
    prompt = (
        f"## CONTEXT FOR THIS RUN\n"
        f"- RUN_DATE = {RUN_DATE}\n"
        f"- RUN_DATE_HUMAN = {RUN_DATE_HUMAN}\n"
        f"- Repo root: current working directory (all file paths are relative to it).\n"
        f"- Do NOT run `git push` — the CI pipeline handles pushing after this script exits.\n"
        f"\n---\n\n"
        f"{original_prompt}"
    )

    messages = [{"role": "user", "content": prompt}]
    print(f"[{RUN_DATE}] Starting daily digest run...")

    turn = 0
    while True:
        turn += 1
        print(f"  → Turn {turn}: calling Claude API...")

        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=16000,
            tools=TOOLS,
            messages=messages,
        )
        print(f"     stop_reason={response.stop_reason}, usage={response.usage}")
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            print("  ✓ Claude finished.")
            for block in response.content:
                if hasattr(block, "text") and block.text:
                    print("\n=== Final report ===")
                    print(block.text)
            break

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                handler = TOOL_HANDLERS.get(block.name)
                if handler:
                    result = handler(block.input)
                    preview = str(result)[:120].replace("\n", " ")
                    print(f"     [{block.name}] {preview}...")
                else:
                    result = f"[No handler for tool: {block.name}]"

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": str(result),
                })
            messages.append({"role": "user", "content": tool_results})
        else:
            print(f"  Unexpected stop_reason: {response.stop_reason!r}. Stopping.")
            break


if __name__ == "__main__":
    run()
