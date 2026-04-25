"""
ProjectCheck hook - smart SessionStart for per-project wiki integration.

Decision tree:
  project has SessionEnd wiki hook → inject wiki context
  project has .claude/.wiki-declined → exit silently
  neither → inject setup prompt asking user to configure wiki
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

COMPILER_ROOT = Path(__file__).resolve().parent.parent
KNOWLEDGE_DIR = COMPILER_ROOT / "knowledge"
DAILY_DIR = COMPILER_ROOT / "daily"
INDEX_FILE = KNOWLEDGE_DIR / "index.md"

MAX_CONTEXT_CHARS = 20_000
MAX_LOG_LINES = 30


def get_project_root() -> Path:
    """Get the actual project root (captured before cd to compiler in hook command)."""
    project_dir = os.environ.get("WIKI_PROJECT_DIR")
    if project_dir:
        return Path(project_dir).resolve()
    # Fallback: try stdin cwd field
    try:
        data = json.loads(sys.stdin.read())
        if "cwd" in data:
            return Path(data["cwd"]).resolve()
    except Exception:
        pass
    return Path.cwd()


def has_wiki_hooks(project_root: Path) -> bool:
    """Return True if project's .claude settings contain a SessionEnd wiki hook."""
    for filename in ("settings.local.json", "settings.json"):
        settings_path = project_root / ".claude" / filename
        if not settings_path.exists():
            continue
        try:
            data = json.loads(settings_path.read_text(encoding="utf-8"))
            for entry in data.get("hooks", {}).get("SessionEnd", []):
                for hook in entry.get("hooks", []):
                    if "session-end.py" in hook.get("command", ""):
                        return True
        except (json.JSONDecodeError, KeyError, TypeError):
            pass
    return False


def is_wiki_declined(project_root: Path) -> bool:
    return (project_root / ".claude" / ".wiki-declined").exists()


def get_recent_log() -> str:
    today = datetime.now(timezone.utc).astimezone()
    for offset in range(2):
        date = today - timedelta(days=offset)
        log_path = DAILY_DIR / f"{date.strftime('%Y-%m-%d')}.md"
        if log_path.exists():
            lines = log_path.read_text(encoding="utf-8").splitlines()
            recent = lines[-MAX_LOG_LINES:] if len(lines) > MAX_LOG_LINES else lines
            return "\n".join(recent)
    return "(no recent daily log)"


def build_wiki_context() -> str:
    parts = []
    today = datetime.now(timezone.utc).astimezone()
    parts.append(f"## Today\n{today.strftime('%A, %B %d, %Y')}")
    if INDEX_FILE.exists():
        parts.append(f"## Knowledge Base Index\n\n{INDEX_FILE.read_text(encoding='utf-8')}")
    else:
        parts.append("## Knowledge Base Index\n\n(empty - no articles compiled yet)")
    parts.append(f"## Recent Daily Log\n\n{get_recent_log()}")
    context = "\n\n---\n\n".join(parts)
    if len(context) > MAX_CONTEXT_CHARS:
        context = context[:MAX_CONTEXT_CHARS] + "\n\n...(truncated)"
    return context


def build_setup_prompt(project_name: str) -> str:
    hooks_json = (
        f'"SessionStart": [{{"matcher": "", "hooks": [{{"type": "command", '
        f'"command": "cd {COMPILER_ROOT} && uv run python hooks/session-start.py", "timeout": 15}}]}}],\n'
        f'"SessionEnd": [{{"matcher": "", "hooks": [{{"type": "command", '
        f'"command": "cd {COMPILER_ROOT} && uv run python hooks/session-end.py", "timeout": 10}}]}}],\n'
        f'"PreCompact": [{{"matcher": "", "hooks": [{{"type": "command", '
        f'"command": "cd {COMPILER_ROOT} && uv run python hooks/pre-compact.py", "timeout": 10}}]}}]'
    )
    return (
        f"WIKI SETUP REQUIRED: Проект `{project_name}` ще не підключений до персональної вікі (Global-AI-Memory).\n\n"
        "Запитай користувача на початку сесії:\n"
        '**"Підключити цей проект до персональної вікі?"**\n\n'
        "- **Так** → додай наступні хуки в секцію `hooks` файлу `.claude/settings.local.json` "
        "(зроби merge, не перезаписуй існуючі permissions):\n"
        f"```json\n{hooks_json}\n```\n"
        "- **Ні** → створи файл `.claude/.wiki-declined` в корені проекту (порожній файл).\n\n"
        "Рішення зберігається — більше не питай про це в цьому проекті."
    )


def output(context: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": context,
        }
    }))


def main():
    project_root = get_project_root()

    # Compiler project and wiki root always get wiki context
    if project_root == COMPILER_ROOT or project_root == COMPILER_ROOT.parent:
        output(build_wiki_context())
        return

    if has_wiki_hooks(project_root):
        output(build_wiki_context())
        return

    if is_wiki_declined(project_root):
        return  # Silent exit

    output(build_setup_prompt(project_root.name))


if __name__ == "__main__":
    main()
