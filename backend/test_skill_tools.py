"""
Deterministic tests for skill tool schemas and RAG start-up behaviour.

- Every registered skill tool takes its input model's fields directly, so a
  tool call like the one the model actually makes validates (it used to fail
  against the single ``params_json`` string and make the ReAct loop retry).
- ``load_skill`` accepts its parameters as an object or a JSON string.
- The HuggingFace embedding load goes local-only once the model is cached.
- A failing knowledge-base warm-up never blocks serving.
"""
import asyncio
import json
import unittest
from unittest.mock import patch

from skills import get_agent_tools, get_registry, load_skill


class SkillToolSchemaTests(unittest.IsolatedAsyncioTestCase):
    def _tool(self, name):
        return get_registry().get_tool(name)

    async def test_symptom_scorer_accepts_direct_fields(self):
        tool = self._tool("symptom_scorer")
        self.assertIn("symptoms_text", tool.args)
        self.assertNotIn("params_json", tool.args)
        raw = await tool.ainvoke({"symptoms_text": "头疼三天，比较严重", "duration_days": 3})
        out = json.loads(raw)
        self.assertEqual(out["skill_name"], "symptom_scorer")
        self.assertTrue(out["success"])
        self.assertTrue(out["disclaimer"])

    async def test_a_tool_call_message_with_direct_fields_validates(self):
        tool = self._tool("symptom_scorer")
        message = await tool.ainvoke({
            "type": "tool_call", "id": "call_1", "name": "symptom_scorer",
            "args": {"symptoms_text": "头疼三天", "pain_scale": 6, "duration_days": 3},
        })
        self.assertEqual(message.tool_call_id, "call_1")
        self.assertNotEqual(getattr(message, "status", "success"), "error")
        self.assertTrue(json.loads(message.content)["success"])

    def test_every_registered_skill_exposes_its_input_fields(self):
        for meta in get_registry().list_skills():
            with self.subTest(skill=meta["name"]):
                instance = get_registry()._load_instance(meta["name"])
                self.assertIsNotNone(instance.input_schema, "declare input_schema on the skill")
                tool = self._tool(meta["name"])
                self.assertEqual(set(tool.args), set(instance.input_schema.model_fields))

    def test_clinic_agent_tools_have_no_json_string_argument(self):
        for tool in get_agent_tools(tags=["clinic"]):
            with self.subTest(tool=tool.name):
                self.assertNotIn("params_json", tool.args)

    async def test_load_skill_accepts_an_object_or_a_json_string(self):
        params = {"symptoms_text": "头疼三天"}
        as_object = json.loads(await load_skill.ainvoke({"skill_name": "symptom_scorer", "params_json": params}))
        as_string = json.loads(await load_skill.ainvoke(
            {"skill_name": "symptom_scorer", "params_json": json.dumps(params, ensure_ascii=False)}
        ))
        self.assertTrue(as_object["success"])
        self.assertEqual(as_object["score"], as_string["score"])
        bad = json.loads(await load_skill.ainvoke({"skill_name": "symptom_scorer", "params_json": "[1]"}))
        self.assertFalse(bad["success"])


class SkillFailureIsolationTests(unittest.TestCase):
    def _registry_with_a_broken_skill(self):
        from pathlib import Path

        from skills import SkillRegistry

        registry = SkillRegistry()
        registry._meta["broken_skill"] = {
            "name": "broken_skill",
            "description": "always fails to import",
            "tags": ["clinic"],
            "_dir": Path("/nonexistent/broken_skill"),
        }
        return registry

    def test_one_broken_skill_does_not_take_down_the_others(self):
        import contextlib
        import io

        registry = self._registry_with_a_broken_skill()
        log = io.StringIO()
        with contextlib.redirect_stdout(log):
            first = registry.get_agent_tools(tags=["clinic"])
            second = registry.get_agent_tools(tags=["clinic"])
        names = {tool.name for tool in first}
        self.assertIn("symptom_scorer", names)
        self.assertNotIn("broken_skill", names)
        self.assertEqual({tool.name for tool in second}, names)
        self.assertEqual(log.getvalue().count("broken_skill"), 1, "logged once")

    def test_a_broken_skill_tool_on_its_own_is_none(self):
        self.assertIsNone(self._registry_with_a_broken_skill().get_tool("broken_skill"))


class EmbeddingLoadTests(unittest.TestCase):
    def _kwargs(self, cached: bool):
        from rag import embeddings

        captured = {}

        class _FakeHF:
            def __init__(self, **kwargs):
                captured.update(kwargs)

        with patch.dict("os.environ", {"EMBEDDING_PROVIDER": "huggingface", "EMBEDDING_MODEL": ""}), patch.object(
            embeddings, "_hf_model_is_cached", return_value=cached
        ), patch("langchain_huggingface.HuggingFaceEmbeddings", _FakeHF):
            embeddings.get_embeddings()
        return captured["model_kwargs"]

    def test_cached_model_loads_without_the_network(self):
        self.assertTrue(self._kwargs(cached=True).get("local_files_only"))

    def test_uncached_model_may_still_download(self):
        self.assertNotIn("local_files_only", self._kwargs(cached=False))

    def test_cache_check_is_offline(self):
        from rag.embeddings import _hf_model_is_cached

        self.assertFalse(_hf_model_is_cached("nobody/definitely-not-a-cached-model"))


class WarmUpTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_failing_warm_up_is_logged_and_swallowed(self):
        with patch("dotenv.load_dotenv"):
            import main

        class _BrokenKb:
            async def warm(self):
                raise RuntimeError("index missing")

        with patch("rag.knowledge_base.get_knowledge_base", return_value=_BrokenKb()):
            await main._warm_knowledge_base()  # must not raise

    async def test_lifespan_does_not_wait_for_the_warm_up(self):
        with patch("dotenv.load_dotenv"):
            import main

        started = asyncio.Event()

        async def slow_warm():
            started.set()
            await asyncio.sleep(10)

        with patch.object(main, "_warm_knowledge_base", slow_warm), patch.object(main, "_close_checkpointer"):
            async with main.lifespan(main.app):
                await asyncio.wait_for(started.wait(), 1)  # serving while warming


if __name__ == "__main__":
    unittest.main()
