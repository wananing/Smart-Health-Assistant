"""
Shared State definitions for the LangGraph multi-agent system.
All state types used across agents are defined here.
"""
from typing import TypedDict, Annotated, Sequence
import operator
from langchain_core.messages import BaseMessage


class MainAgentState(TypedDict):
    """
    Global state shared between the Router and all Specialized Agents.
    This is the 'single source of truth' for the current conversation turn.
    """
    # Accumulated conversation history (append-only via operator.add)
    messages: Annotated[Sequence[BaseMessage], operator.add]

    # User profile info injected by the API layer (name, age, medical history, etc.)
    user_info: dict

    # The agent the Router decided to dispatch to, e.g., "clinic_agent", "insurance_agent"
    next_agent: str
    
    # Persistent tracking of the current focused agent to handle multi-turn conversations
    # If set, the router should bypass standard classification and route back here.
    active_agent: str
