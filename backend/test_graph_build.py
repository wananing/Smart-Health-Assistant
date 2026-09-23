import os
import unittest
from unittest.mock import patch

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph.state import CompiledStateGraph

from agents.checkpointing import (
    CheckpointerConfigurationError,
    create_checkpointer,
    resolve_checkpoint_db_path,
    resolve_checkpointer_backend,
)
from agents.graph import build_graph


class CheckpointerConfigurationTests(unittest.TestCase):
    def test_memory_is_the_default_backend(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(resolve_checkpointer_backend(), "memory")
            self.assertIsInstance(create_checkpointer(), MemorySaver)

    def test_sqlite_backend_is_recognised_with_a_default_path(self):
        with patch.dict(os.environ, {"CHECKPOINTER": "sqlite"}, clear=True):
            self.assertEqual(resolve_checkpointer_backend(), "sqlite")
            self.assertEqual(resolve_checkpoint_db_path(), "checkpoints.sqlite")

        with patch.dict(
            os.environ,
            {"CHECKPOINTER": "sqlite", "CHECKPOINT_DB_PATH": "/tmp/bigh.sqlite"},
            clear=True,
        ):
            self.assertEqual(resolve_checkpoint_db_path(), "/tmp/bigh.sqlite")

    def test_unknown_backend_is_rejected(self):
        with patch.dict(os.environ, {"CHECKPOINTER": "redis"}, clear=True):
            with self.assertRaises(CheckpointerConfigurationError):
                resolve_checkpointer_backend()


class MasterGraphBuildTests(unittest.TestCase):
    def test_master_graph_compiles_with_a_checkpointer(self):
        app = build_graph(checkpointer=MemorySaver())
        self.assertIsInstance(app.checkpointer, BaseCheckpointSaver)

    def test_clinic_node_is_a_compiled_subgraph(self):
        app = build_graph(checkpointer=MemorySaver())
        clinic = app.nodes["clinic_node"].bound
        self.assertIsInstance(clinic, CompiledStateGraph)

        inner_nodes = set(clinic.nodes)
        self.assertLessEqual(
            {
                "emergency_gate",
                "extract_symptoms",
                "check_sufficiency",
                "ask_followup",
                "await_answer",
                "conclude",
            },
            inner_nodes,
        )

    def test_xray_diagram_expands_the_clinic_subgraph(self):
        app = build_graph(checkpointer=MemorySaver())
        mermaid = app.get_graph(xray=1).draw_mermaid()
        self.assertIn("subgraph clinic_node", mermaid)
        self.assertIn("emergency_gate", mermaid)

    def test_other_agent_nodes_stay_plain_callables(self):
        app = build_graph(checkpointer=MemorySaver())
        for node_name in ("insurance_node", "report_node", "advisor_node", "pharmacy_node"):
            self.assertNotIsInstance(app.nodes[node_name].bound, CompiledStateGraph)


if __name__ == "__main__":
    unittest.main()
