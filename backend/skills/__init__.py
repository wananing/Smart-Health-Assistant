"""
Skill Registry — auto-discovery, loading, and LangChain tool wrapping.

How it works:
  1. On import, scans backend/skills/*/SKILL.md for installed skills
  2. Reads frontmatter (name, description, tags) without executing skill code
  3. Lazily imports the skill class on first use (avoids heavy imports at startup)
  4. Wraps each skill as a LangChain @tool so ReAct agents can invoke it

Agent integration:
  from skills import get_agent_tools
  tools = get_agent_tools(tags=["clinic"])   # returns list[BaseTool]

  # Or let an agent call any skill by name at runtime:
  from skills import load_skill_tool
  # add load_skill_tool to the agent's tool list
"""
from __future__ import annotations

import importlib
import json
import re
from pathlib import Path
from typing import Any

from langchain_core.tools import tool

from skills.base import BaseSkill

_SKILLS_DIR = Path(__file__).parent

# ─── SKILL.md frontmatter parser ──────────────────────────────────────────────

def _parse_frontmatter(skill_md: Path) -> dict:
    """
    Parse the YAML-like frontmatter block from a SKILL.md file.
    Returns a dict with at least {name, description, tags}.
    """
    text = skill_md.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    if not match:
        return {}

    fm: dict = {}
    block = match.group(1)

    # Simple line-by-line YAML parser (no external dependency)
    current_key = None
    current_multiline: list[str] = []

    for line in block.splitlines():
        if line.startswith("  ") and current_key and current_multiline is not None:
            current_multiline.append(line.strip())
            continue

        if current_key and current_multiline:
            fm[current_key] = " ".join(current_multiline).strip()
            current_key = None
            current_multiline = []

        if ": " in line or line.endswith(":"):
            key, _, val = line.partition(": ")
            key = key.strip()
            val = val.strip()

            if val == "|":
                current_key = key
                current_multiline = []
            elif val.startswith("[") and val.endswith("]"):
                # Inline list: [a, b, c]
                items = [i.strip() for i in val[1:-1].split(",")]
                fm[key] = items
            else:
                fm[key] = val

    if current_key and current_multiline:
        fm[current_key] = " ".join(current_multiline).strip()

    # Ensure tags is always a list
    if "tags" not in fm:
        fm["tags"] = []
    elif isinstance(fm["tags"], str):
        fm["tags"] = [t.strip() for t in fm["tags"].split(",")]

    return fm


# ─── Registry ─────────────────────────────────────────────────────────────────

class SkillRegistry:
    """
    Auto-discovers all skills by scanning for SKILL.md files.
    Provides lazy loading and LangChain tool wrapping.
    """

    def __init__(self) -> None:
        self._meta: dict[str, dict] = {}       # name → frontmatter dict
        self._instances: dict[str, BaseSkill] = {}  # name → skill instance (lazy)
        self._scan()

    def _scan(self) -> None:
        for skill_md in sorted(_SKILLS_DIR.glob("*/SKILL.md")):
            meta = _parse_frontmatter(skill_md)
            if "name" not in meta:
                continue
            meta["_dir"] = skill_md.parent
            self._meta[meta["name"]] = meta

    def list_skills(self, tags: list[str] | None = None) -> list[dict]:
        """Return metadata for all registered skills, optionally filtered by tag."""
        results = []
        for meta in self._meta.values():
            if tags is None:
                results.append(meta)
            elif any(t in meta.get("tags", []) for t in tags):
                results.append(meta)
        return results

    def _load_instance(self, name: str) -> BaseSkill:
        """Lazily import and instantiate the skill class from its subdirectory."""
        if name in self._instances:
            return self._instances[name]

        meta = self._meta.get(name)
        if meta is None:
            raise KeyError(f"Skill '{name}' not found in registry")

        skill_dir = meta["_dir"]
        # Import skill.py from the skill's subdirectory
        module_name = f"skills.{skill_dir.name}.skill"
        try:
            mod = importlib.import_module(module_name)
        except ModuleNotFoundError as e:
            raise ImportError(f"Cannot load skill '{name}': {e}") from e

        # Find the BaseSkill subclass in the module
        skill_cls = None
        for attr_name in dir(mod):
            attr = getattr(mod, attr_name)
            if (
                isinstance(attr, type)
                and issubclass(attr, BaseSkill)
                and attr is not BaseSkill
            ):
                skill_cls = attr
                break

        if skill_cls is None:
            raise ImportError(f"No BaseSkill subclass found in {module_name}")

        instance = skill_cls()
        self._instances[name] = instance
        return instance

    def get_tool(self, name: str):
        """
        Return a LangChain @tool function wrapping the named skill.
        The tool accepts a JSON string of keyword arguments.
        """
        meta = self._meta[name]
        description = meta.get("description", f"Skill: {name}").replace("\n", " ").strip()

        registry_ref = self  # capture for closure

        @tool(name, description=description)
        async def _skill_tool(params_json: str = "{}") -> str:
            """Execute a registered skill. params_json is a JSON object of keyword arguments."""
            try:
                kwargs: dict[str, Any] = json.loads(params_json) if params_json.strip() else {}
            except json.JSONDecodeError:
                kwargs = {}

            skill_instance = registry_ref._load_instance(name)
            result = await skill_instance.arun(**kwargs)
            return result.model_dump_json(ensure_ascii=False)

        return _skill_tool

    def get_agent_tools(self, tags: list[str]) -> list:
        """
        Return LangChain tools for all skills whose tags overlap with the
        requested agent tags. Ready to pass directly to create_react_agent().
        """
        tools = []
        for meta in self._meta.values():
            skill_tags = meta.get("tags", [])
            if any(t in skill_tags for t in tags):
                tools.append(self.get_tool(meta["name"]))
        return tools


# ─── Singleton ────────────────────────────────────────────────────────────────

_registry: SkillRegistry | None = None


def get_registry() -> SkillRegistry:
    """Return the process-wide singleton skill registry."""
    global _registry
    if _registry is None:
        _registry = SkillRegistry()
    return _registry


def get_agent_tools(tags: list[str]) -> list:
    """
    Convenience shortcut: get LangChain tools for the given agent tags.

    Usage in an agent node:
        from skills import get_agent_tools
        skill_tools = get_agent_tools(["clinic"])
        agent = create_react_agent(llm, tools=[*core_tools, *skill_tools], ...)
    """
    return get_registry().get_agent_tools(tags)


# ─── Runtime load_skill tool ──────────────────────────────────────────────────
# This tool can be added to ANY agent's tool list, allowing the agent to
# discover and invoke skills by name at runtime — without the registry needing
# to pre-load all of them.

@tool
async def load_skill(skill_name: str, params_json: str = "{}") -> str:
    """
    Load and execute any registered skill by name at runtime.

    Args:
        skill_name:  The skill's name (e.g. 'health_calculator', 'symptom_scorer').
        params_json: A JSON object string with the skill's input parameters.

    Returns a JSON string with the skill's structured output including
    a 'disclaimer' field that must be shown to the user.

    Available skills:
      health_calculator  — BMI, ideal weight, daily calorie needs
      symptom_scorer     — Severity score + triage colour for symptoms
      lab_interpreter    — Lab value abnormality detection + clinical notes
      risk_assessor      — 10-year CVD and diabetes risk (Framingham + FINDRISC)
      emergency_triage   — Fast safety gate for life-threatening symptoms
      medication_calculator — Weight/age-based dose calculation
    """
    registry = get_registry()
    try:
        instance = registry._load_instance(skill_name)
    except KeyError:
        available = [m["name"] for m in registry.list_skills()]
        return json.dumps({
            "success": False,
            "error": f"Skill '{skill_name}' not found.",
            "available_skills": available,
        }, ensure_ascii=False)

    try:
        kwargs: dict[str, Any] = json.loads(params_json) if params_json.strip() else {}
    except json.JSONDecodeError:
        return json.dumps({"success": False, "error": "params_json is not valid JSON"})

    result = await instance.arun(**kwargs)
    return result.model_dump_json(ensure_ascii=False)
