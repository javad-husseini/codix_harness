"""Build-time check: fail before freezing if native Windows wheels cannot import."""
import pydantic_core
from langgraph.graph import StateGraph
print('Windows native-extension and LangGraph imports passed.')
