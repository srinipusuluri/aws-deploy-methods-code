"""Level 5 - Claude proposes tool calls; the backend validates, authorizes and executes.

POST /agent          {message}            -> {answer, pendingActions[]}
POST /agent/approve  {actionId}           -> executes a queued write tool"""
import json

from shared.common import HttpError, clean_text, handler, log, parse_json, reply, user_from_event
from shared.providers import get_provider
from level5_agent import tools

SYSTEM = ("You are a customer-support assistant. Use tools to look up the customer's own orders. "
          "Write actions are queued and need the customer's approval; tell them so.")
MAX_LOOPS = 4


def agent_turn(text, user, provider=None, run_read=None, queue_write=None):
    provider = provider or get_provider()
    run_read = run_read or tools.run_read_tool
    queue_write = queue_write or tools.queue_write_tool
    messages, pending = [{"role": "user", "content": text}], []
    for _ in range(MAX_LOOPS):
        out = provider.generate(messages, system=SYSTEM, max_tokens=800, tools=tools.TOOL_DEFS)
        if out["stop_reason"] != "tool_use":
            answer = out["text"]
            if out["stop_reason"] == "max_tokens":
                answer += "\n\n(The answer was cut off.)"
            return {"answer": answer, "pendingActions": pending}
        messages.append({"role": "assistant", "content": out["content"]})
        results = []
        for block in out["content"]:
            if block.type != "tool_use":
                continue
            try:
                if block.name in tools.WRITE_TOOLS:
                    aid = queue_write(block.name, block.input, user)
                    pending.append({"actionId": aid, "tool": block.name, "args": block.input})
                    content = f"Queued for customer approval (actionId {aid}). Not executed yet."
                else:
                    content = json.dumps(run_read(block.name, block.input, user), default=str)
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": content})
            except tools.ToolError as e:
                results.append({"type": "tool_result", "tool_use_id": block.id, "is_error": True, "content": str(e)})
            except Exception:
                log.exception("tool failed name=%s", block.name)
                results.append({"type": "tool_result", "tool_use_id": block.id, "is_error": True,
                                "content": "Tool failed."})
        messages.append({"role": "user", "content": results})
    raise HttpError(502, "The assistant needed too many steps. Please rephrase.")


@handler
def lambda_handler(event, context):
    user = user_from_event(event)
    body = parse_json(event)
    if event.get("routeKey") == "POST /agent/approve":
        try:
            return reply(200, tools.approve_action(clean_text(body.get("actionId"), "actionId", 64), user))
        except tools.ToolError as e:
            raise HttpError(409, str(e))
    return reply(200, agent_turn(clean_text(body.get("message"), "message"), user))
