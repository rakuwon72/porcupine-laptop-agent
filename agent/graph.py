"""The LangGraph agent: a small loop between "Claude thinks" and "run tools".

          +-----------+   tool calls?   +-------+
 START -> |   model   | --------------> | tools |
          +-----------+ <-------------- +-------+
                |            results
                | no tool calls
                v
               END  (final answer shown to the user)

Safety nets that make it behave sensibly when a task is hard:
  - the SAME tool call can't be repeated again and again (loop / duplicate guard)
  - when stuck, the work moves to a STRONGER model
  - after too many steps it stops and gives an honest report (no silent failure)
"""

import json
from collections import Counter

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.types import interrupt

from agent import events
from agent.config import (
    ESCALATE_AFTER_TOOL_CALLS, ESCALATE_WHEN_STUCK, MODEL_NAME, READ_ONLY_REPEAT_LIMIT,
    READ_ONLY_TOOLS, REPEAT_LIMIT, SMART_MODEL_NAME, SOFT_STEP_LIMIT,
)
from agent.manifest import manifest_summary
from agent.memory import memory_summary
from agent.learn_tools import LEARN_TOOLS
from agent.phone_bridge import PHONE_TOOLS
from agent.profile import summary_for_prompt as profile_fields
from agent.signup_tools import SIGNUP_TOOLS
from agent.tools import TOOLS, needs_confirmation
from agent.web_tools import search_web

# Everything the agent can do: the basic tools + "learn new sites" + "send to phone"
# + "fill sign-up forms from the profile" + "search the web"
ALL_TOOLS = TOOLS + LEARN_TOOLS + PHONE_TOOLS + SIGNUP_TOOLS + [search_web]

# Lookup table so we can find a tool by the name Claude asked for
TOOLS_BY_NAME = {t.name: t for t in ALL_TOOLS}


def build_system_prompt() -> str:
    """Instructions given to Claude on every turn, including the manifest."""
    return (
        "You are an assistant that controls the user's Windows laptop through tools.\n"
        "You can ONLY use the apps and websites listed below.\n\n"
        f"{manifest_summary()}\n\n"
        "WHAT YOU REMEMBER ABOUT THE USER (from earlier sessions):\n"
        f"{memory_summary()}\n\n"
        "PERSONAL PROFILE FIELDS you can fill forms with (these are only the NAMES - the values are "
        "private and you never see them; fill_form_from_profile types them for you):\n"
        f"{profile_fields()}\n\n"
        "Rules:\n"
        "- Use the tools to carry out the user's request.\n"
        "- To control an app: open_app first, then do_app_action with an action listed for it.\n"
        "- To read a result (e.g. calculator answer), use the app's read action and tell the user.\n"
        "- For files: search_files to find them, open_path to open them. Never guess a path.\n"
        "- If a site needs a login, open it and call sign_in. You never see passwords.\n"
        "- If sign_in says nothing is saved, tell the user to run add_password.py. "
        "NEVER ask the user for a password in the chat and never repeat or guess one.\n"
        "- If a page has a CAPTCHA, the user must solve it themselves - tell them and wait.\n"
        "- If a site is open in a browser and the user wants to navigate further, use the browser's go_to action.\n"
        "- To act INSIDE a website (e.g. write an email): open_website first, then do_site_action.\n"
        "- Emails: get the recipient, subject and message from the user (ask_user only if one is missing). "
        "If the user said to send, write the email AND send it in the same go. "
        "If they only said to write or draft it, do not send.\n"
        "- To know what is on a page (inbox, message, postings), call read_page, then answer from its text.\n"
        "- Inbox: open_inbox, then read_page to list messages; open_message (part of a subject), "
        "then read_page to read it; search_mail to find mails; reply then write_reply to answer.\n"
        "- When the user states a lasting fact or preference, save it with remember. Never remember secrets.\n"
        "\n"
        "HOW TO WORK CAREFULLY (very important):\n"
        "- LOOK BEFORE YOU ACT: use read_page / list_controls to see the real page first. Use the "
        "EXACT control names from list_controls. If ui_click says several controls matched, read the "
        "list and choose with index=N - do not just retry the same name.\n"
        "- VERIFY: ui_type reads the field back. If it says WARNING, the text is NOT where you "
        "wanted it: do NOT press Enter. Fix the target first.\n"
        "- SEND EXACTLY ONCE: never send or submit the same message twice. If you are unsure whether "
        "something was sent, read_page and check BEFORE trying again. Check the page afterwards to "
        "confirm it worked.\n"
        "- NEVER repeat an identical tool call. If something did not work, change your approach.\n"
        "- GIVE UP HONESTLY: after about 3 failed attempts at the same step, stop and tell the user "
        "plainly what you did, what failed, and what they could check - do not keep trying variations.\n"
        "- RECOVERY: a failed tool's error message often lists similar controls - use them. "
        "Otherwise call list_controls and use ui_click / ui_type.\n"
        "\n"
        "- UNKNOWN WEBSITE (not in the manifest)? NEVER stop with 'it's not in my list'. Call "
        "search_web('<name> official site') to find its real address, choose the OFFICIAL domain (the one "
        "that matches the brand - avoid look-alike or unrelated domains), and open it with "
        "learn_website(name, url), which also remembers it. Say which domain you used. Only ask the user "
        "if the search finds nothing convincing or several brands fit.\n"
        "- CREATE AN ACCOUNT: open the site (as above), go to its sign-up page (ui_click 'Sign up' etc.), "
        "then call fill_form_from_profile(<site name>, generate_password=True) - never type the user's "
        "personal details yourself, you do not have them. It never ticks the Terms boxes, never solves "
        "CAPTCHAs and never presses the final button: after it, tell the user exactly what is left "
        "(review, tick terms, CAPTCHA, email/SMS code, press Create account). If the profile is empty, "
        "tell them to run python add_profile.py.\n"
        "- NEW SITE not in the manifest? LEARN it: learn_website(name, url), look with read_page / list_controls, do the task with "
        "ui_click / ui_type / ui_press, then save_learned_action so next time one do_site_action "
        "call is enough. Prefer saving a general action (e.g. search_site with the query as `text`). "
        "Use a saved action instead of exploring again whenever the manifest lists one. "
        "Only save an action after the task REALLY worked.\n"
        "- PHONE: a request that starts with '(From the user's phone' came from their phone; they cannot "
        "see the laptop screen, so describe results in words. To give them a file, find it with "
        "search_files and call send_to_phone.\n"
        "- TEACH BY SHOWING: if the user wants to show you how to do something, call start_teaching(target), "
        "then tell them to do it ONCE and say 'done'. When they say done, call finish_teaching "
        "(pick a good action_name and describe the inputs). Never start recording on your own.\n"
        "- Never type the user's password yourself. For a login, use sign_in; for a learned site, "
        "first teach it an 'autofill_login' action (click the username field, ui_press down, "
        "ui_press enter) and save it, so Edge fills the saved login.\n"
        "- Do not ask for permission or confirmation. When the user tells you to do something, do it. "
        "Only ask when information is truly missing.\n"
        "- If something is missing or unclear, call ask_user. Do not guess.\n"
        "- If the user wants something that is not in the manifest, tell them.\n"
        "- When finished, reply with one short sentence saying what you did."
    )


# ---------------------------------------------------------------- looking at the current request

def _current_request(messages: list) -> list:
    """The messages since the user's LATEST message - i.e. what happened in this one request."""
    last_human = max((i for i, m in enumerate(messages) if m.type == "human"), default=-1)
    return messages[last_human + 1:]


def _tool_calls_used(messages: list) -> int:
    """How many tool calls have already run in the current request."""
    return sum(1 for m in _current_request(messages) if m.type == "tool")


def _call_key(call: dict) -> str:
    """A fingerprint of a tool call (its name + arguments) for spotting repeats."""
    return call["name"] + json.dumps(call["args"], sort_keys=True, default=str)


def build_graph():
    """Create and compile the agent graph."""
    # The everyday model (cheap and fast) and the stronger one used when stuck.
    # Both know about our tools.
    model = ChatAnthropic(model=MODEL_NAME).bind_tools(ALL_TOOLS)
    smart_model = ChatAnthropic(model=SMART_MODEL_NAME).bind_tools(ALL_TOOLS)

    # ---- Node 1: Claude decides what to do next ----
    def call_model(state: MessagesState):
        events.emit("thinking")  # tell the UI Claude is deciding what to do
        used = _tool_calls_used(state["messages"])
        system = build_system_prompt()

        # Safety net 1: too many steps -> stop, and report honestly instead of looping on
        if used >= SOFT_STEP_LIMIT:
            note = (f"\n\nSTOP. You have already made {used} tool calls for this request and it is "
                    "not finished. Do NOT call any more tools. Write a short, honest report for the "
                    "user: what you managed to do, what did NOT work and why you think so, and "
                    "anything they should double-check themselves (for example a message that may "
                    "or may not have been sent).")
            reply = smart_model.invoke([SystemMessage(system + note)] + state["messages"])
            text = reply.text or ("I ran out of steps before finishing. Please check the screen to "
                                  "see how far I got, then tell me what to do next.")
            return {"messages": [AIMessage(content=text)]}   # plain text only -> the graph ends

        # Safety net 2: struggling -> let the stronger model take over for the rest of this request
        struggling = ESCALATE_WHEN_STUCK and used >= ESCALATE_AFTER_TOOL_CALLS
        chosen = smart_model if struggling else model
        return {"messages": [chosen.invoke([SystemMessage(system)] + state["messages"])]}

    # ---- Node 2: run whatever tools Claude asked for ----
    def run_tools(state: MessagesState, config: RunnableConfig):
        last_message = state["messages"][-1]
        calls = last_message.tool_calls
        # A session can force "ask before risky actions" on or off (the phone session forces it on)
        force_confirm = config.get("configurable", {}).get("confirm_risky")

        # What has already been called in this request (to catch loops and duplicates)
        earlier = Counter(
            _call_key(c)
            for m in _current_request(state["messages"][:-1])
            if m.type == "ai"
            for c in m.tool_calls
        )

        # IMPORTANT: every step that can PAUSE the graph (questions and
        # confirmations) happens BEFORE any real action runs. When the graph
        # resumes, this node restarts from the top, so doing the pausing first
        # means no action (like typing text) is ever repeated.
        results = []

        # Step 1: questions for the user
        for call in [c for c in calls if c["name"] == "ask_user"]:
            answer = TOOLS_BY_NAME["ask_user"].invoke(call["args"])
            results.append(ToolMessage(content=str(answer), tool_call_id=call["id"]))

        # Step 2: ask permission for risky actions (marked "confirm" in the manifest)
        approved = []
        for call in [c for c in calls if c["name"] != "ask_user"]:
            question = needs_confirmation(call["name"], call["args"], force_confirm)
            if question and not str(interrupt(question)).strip().lower().startswith("y"):
                results.append(ToolMessage(content="The user declined this action.", tool_call_id=call["id"]))
            else:
                approved.append(call)

        # Step 3: finally run the approved actions
        for call in approved:
            # Safety net 3: refuse an identical call that was already made too often
            limit = READ_ONLY_REPEAT_LIMIT if call["name"] in READ_ONLY_TOOLS else REPEAT_LIMIT
            key = _call_key(call)
            if earlier[key] >= limit:
                results.append(ToolMessage(
                    content=(f"BLOCKED: you already made this exact call {earlier[key]} times in this "
                             "request. Repeating it will not help (and could send or type something "
                             "twice). Check the screen with read_page / list_controls and try a "
                             "DIFFERENT approach, or stop and tell the user what is blocking you."),
                    tool_call_id=call["id"]))
                continue
            earlier[key] += 1   # also counts repeats inside this very batch

            events.emit("tool", name=call["name"], args=call["args"])  # announce it first
            try:
                output = TOOLS_BY_NAME[call["name"]].invoke(call["args"])
            except Exception as error:  # let Claude see the error and recover
                output = f"Tool error: {error}"
            results.append(ToolMessage(content=str(output), tool_call_id=call["id"]))
        return {"messages": results}

    # ---- Decide where to go after Claude speaks ----
    def route(state: MessagesState):
        # If Claude asked for tools -> run them, otherwise we are done
        return "tools" if state["messages"][-1].tool_calls else END

    # ---- Wire the nodes together ----
    graph = StateGraph(MessagesState)
    graph.add_node("model", call_model)
    graph.add_node("tools", run_tools)
    graph.add_edge(START, "model")
    graph.add_conditional_edges("model", route, ["tools", END])
    graph.add_edge("tools", "model")  # after tools, Claude looks at the results

    # MemorySaver remembers the conversation and is REQUIRED for pausing
    # (ask_user) and resuming the graph.
    return graph.compile(checkpointer=MemorySaver())
