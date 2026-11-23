"""Level 2 - multi-turn chat. History is supplied by the browser and is NOT trusted."""
from shared.common import HttpError, handler, normalize_messages, parse_json, reply
from shared.providers import get_provider

SYSTEM = "Answer clearly. Use conversation context when relevant."


@handler
def lambda_handler(event, context):
    body = parse_json(event)
    messages = normalize_messages(body.get("messages"))
    out = get_provider().generate(messages, system=SYSTEM, max_tokens=700)
    return reply(200, {"answer": out["text"], "usage": {"in": out["input_tokens"], "out": out["output_tokens"]}})
