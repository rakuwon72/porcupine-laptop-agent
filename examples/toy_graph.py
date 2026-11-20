"""A TINY LangGraph agent, built to teach how the real one (agent/graph.py) works.

It has the exact same shape as the real agent, but the "model" is FAKE (a script),
so it runs with no API key and no cost. Run it:

    python examples/toy_graph.py

Then try the exercises at the bottom.
"""

from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph


# ---------------------------------------------------------------- 1) a TOOL
# A tool is an ordinary Python function with @tool on top.
#   - its NAME comes from the function name              -> "multiply"
#   - its DESCRIPTION comes from the docstring           -> what Claude reads to decide when to use it
#   - its INPUTS come from the type hints (a: int, ...)  -> Claude must send integers
@tool
def multiply(a: int, b: int) -> int:
    """Multiply two whole numbers."""
    return a * b


# ---------------------------------------------------------------- 2) NODE 1: the "model"
# A node is just a function: it receives the STATE (here: the list of messages so far)
# and returns an UPDATE. LangGraph APPENDS returned messages to the list.
# In the real agent this node calls Claude. Here we fake Claude with a tiny script:
def model_node(state: MessagesState):
    last = state["messages"][-1]

    if last.type == "human":
        # First time through: the user just spoke. A real Claude would think and then
        # ASK FOR A TOOL. It does not run the tool - it only writes down the request:
        request = AIMessage(content="", tool_calls=[
            {"name": "multiply", "args": {"a": 245, "b": 18}, "id": "call_1"},
        ])
        return {"messages": [request]}

    # Second time through: the last message is the tool's RESULT, so we can answer.
    return {"messages": [AIMessage(content=f"245 x 18 = {last.content}")]}


# ---------------------------------------------------------------- 3) NODE 2: the "tools"
# This is where tools are really RUN - by our code, not by the AI.
def tools_node(state: MessagesState):
    call = state["messages"][-1].tool_calls[0]       # the request the model wrote down
    result = multiply.invoke(call["args"])           # <-- THE TOOL CALL: run the Python function
    # Wrap the result in a ToolMessage. tool_call_id says WHICH request it answers.
    return {"messages": [ToolMessage(content=str(result), tool_call_id=call["id"])]}


# ---------------------------------------------------------------- 4) the decision (an "edge")
# After the model speaks: if it asked for a tool, go run it; otherwise we are finished.
def route(state: MessagesState):
    return "tools" if state["messages"][-1].tool_calls else END


# ---------------------------------------------------------------- 5) wire the graph together
graph = StateGraph(MessagesState)          # MessagesState = {"messages": [...]} that only ever grows
graph.add_node("model", model_node)
graph.add_node("tools", tools_node)
graph.add_edge(START, "model")                                   # always begin with the model
graph.add_conditional_edges("model", route, ["tools", END])      # then: tools, or finish
graph.add_edge("tools", "model")                                 # after a tool ran, the model looks at the result
app = graph.compile(checkpointer=MemorySaver())                  # the checkpointer remembers a conversation by thread_id


# ---------------------------------------------------------------- 6) run it
print("=== each step the graph takes ===")
config = {"configurable": {"thread_id": "demo"}}      # one conversation = one thread_id
for step in app.stream({"messages": [("user", "what is 245 times 18?")]}, config, stream_mode="updates"):
    for node, update in step.items():
        message = update["messages"][-1]
        print(f"[{node:5}] {message.type:5} | content={message.content!r} | tool_calls={getattr(message, 'tool_calls', None) or '-'}")

print("\n=== the final state: the whole conversation as a list of messages ===")
for message in app.get_state(config).values["messages"]:
    print(f"  {message.type:5}: {message.content!r}")

# ---------------------------------------------------------------- exercises
# 1. Run a SECOND question on the same thread_id: app.invoke({"messages": [("user", "again")]}, config)
#    and print the messages. Notice the whole earlier conversation is still there (the checkpointer).
# 2. Add an "add" tool, and make model_node ask for BOTH tools one after the other.
#    (Hint: count how many "tool" messages are already in state["messages"].)
# 3. Change route() to always return END. What does the program print, and why?
