"""Level 1 - single question, single answer. No login, no database."""
from shared.common import clean_text, handler, parse_json, reply
from shared.providers import get_provider

SYSTEM = "You are a helpful assistant. Be accurate and concise."


@handler
def lambda_handler(event, context):
    question = clean_text(parse_json(event).get("question"), "question")
    out = get_provider().generate([{"role": "user", "content": question}], system=SYSTEM, max_tokens=600)
    return reply(200, {"answer": out["text"]})
