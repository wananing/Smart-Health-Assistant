"""
Main LangGraph StateGraph assembler.

Wires together all agent nodes into the master graph:
  START -> router -> (clinic | insurance | report | advisor) -> END
"""
from langgraph.graph import StateGraph, START, END
from agents.state import MainAgentState
from agents.router import router_node
from agents.clinic import clinic_node
from agents.report import report_node
from agents.advisor import advisor_node
from agents.insurance import insurance_node
from agents.pharmacy import pharmacy_node


# --- Routing function ---
# Maps next_agent string -> the node key in the graph
_AGENT_MAP = {
    "clinic_agent": "clinic_node",
    "insurance_agent": "insurance_node",
    "report_agent": "report_node",
    "advisor_agent": "advisor_node",
    "pharmacy_agent": "pharmacy_node",
}

def _route_to_agent(state: MainAgentState) -> str:
    """Reads next_agent and returns the graph node name to execute next."""
    agent_id = state.get("next_agent", "advisor_agent")
    return _AGENT_MAP.get(agent_id, "advisor_node")


# --- Build the graph ---
def build_graph() -> StateGraph:
    workflow = StateGraph(MainAgentState)

    # 1. Register all nodes
    workflow.add_node("router", router_node)
    workflow.add_node("clinic_node", clinic_node)
    workflow.add_node("insurance_node", insurance_node)
    workflow.add_node("report_node", report_node)
    workflow.add_node("advisor_node", advisor_node)
    workflow.add_node("pharmacy_node", pharmacy_node)

    # 2. Entry point: START -> router
    workflow.add_edge(START, "router")

    # 3. Conditional routing from router -> specialized agent
    workflow.add_conditional_edges(
        "router",
        _route_to_agent,
        {
            "clinic_node": "clinic_node",
            "insurance_node": "insurance_node",
            "report_node": "report_node",
            "advisor_node": "advisor_node",
            "pharmacy_node": "pharmacy_node",
        }
    )

    # 4. All specialized agents -> END
    workflow.add_edge("clinic_node", END)
    workflow.add_edge("insurance_node", END)
    workflow.add_edge("report_node", END)
    workflow.add_edge("advisor_node", END)
    workflow.add_edge("pharmacy_node", END)

    return workflow.compile()


# Singleton compiled graph instance used by main.py
master_app = build_graph()
