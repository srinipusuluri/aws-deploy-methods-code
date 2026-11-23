"""Level 3 - Cognito login + DynamoDB chat history. Also used by Level 6 (adds quota).

Routes:  POST /chat   {chatId?, message}
         GET  /chats
         GET  /chats/{chatId}
         DELETE /chats/{chatId}
Every key is built from the JWT `sub`, never from request JSON."""
import os, time, uuid

import boto3
from boto3.dynamodb.conditions import Key

from shared.common import HttpError, check_quota, clean_text, handler, log, normalize_messages, parse_json, reply, user_from_event
from shared.providers import get_provider

SYSTEM = "You are a helpful assistant. Use the conversation so far when relevant."
HISTORY_LIMIT = 20

_ddb = None


def tables():
    global _ddb
    if _ddb is None:
        r = boto3.resource("dynamodb")
        _ddb = (r.Table(os.environ["SESSIONS_TABLE"]), r.Table(os.environ["MESSAGES_TABLE"]))
    return _ddb


def now_ms():
    return int(time.time() * 1000)


def save_message(messages_table, sub, chat_id, role, content):
    ts = now_ms()
    messages_table.put_item(Item={
        "pk": f"USER#{sub}", "sk": f"CHAT#{chat_id}#MSG#{ts:013d}#{uuid.uuid4().hex[:8]}",
        "role": role, "content": content[:8000], "createdAt": ts})


def load_messages(messages_table, sub, chat_id, limit=HISTORY_LIMIT):
    res = messages_table.query(
        KeyConditionExpression=Key("pk").eq(f"USER#{sub}") & Key("sk").begins_with(f"CHAT#{chat_id}#MSG#"),
        ScanIndexForward=False, Limit=limit)          # newest first so Limit keeps the latest turns
    return [{"role": x["role"], "content": x["content"], "createdAt": int(x["createdAt"])}
            for x in reversed(res.get("Items", []))]


def get_session(sessions_table, sub, chat_id):
    return sessions_table.get_item(Key={"pk": f"USER#{sub}", "sk": f"CHAT#{chat_id}"}).get("Item")


def chat(event, user):
    sessions, msgs = tables()
    body = parse_json(event)
    text = clean_text(body.get("message"), "message")
    chat_id = body.get("chatId")
    if chat_id:
        if not get_session(sessions, user["sub"], str(chat_id)):      # ownership check
            raise HttpError(404, "Chat not found.")
    else:
        chat_id = uuid.uuid4().hex
        sessions.put_item(Item={"pk": f"USER#{user['sub']}", "sk": f"CHAT#{chat_id}",
                                "title": text[:60], "createdAt": now_ms(), "updatedAt": now_ms()})
    check_quota(f"USER#{user['sub']}")
    save_message(msgs, user["sub"], chat_id, "user", text)
    history = normalize_messages(load_messages(msgs, user["sub"], chat_id))
    out = get_provider().generate(history, system=SYSTEM, max_tokens=700)
    save_message(msgs, user["sub"], chat_id, "assistant", out["text"])
    sessions.update_item(Key={"pk": f"USER#{user['sub']}", "sk": f"CHAT#{chat_id}"},
                         UpdateExpression="SET updatedAt = :u", ExpressionAttributeValues={":u": now_ms()})
    log.info("chat ok tokens_in=%s tokens_out=%s", out["input_tokens"], out["output_tokens"])
    return reply(200, {"chatId": chat_id, "answer": out["text"]})


def list_chats(user):
    sessions, _ = tables()
    res = sessions.query(KeyConditionExpression=Key("pk").eq(f"USER#{user['sub']}"))
    items = sorted(res.get("Items", []), key=lambda i: i.get("updatedAt", 0), reverse=True)
    return reply(200, {"chats": [{"chatId": i["sk"].split("#", 1)[1], "title": i.get("title", ""),
                                  "updatedAt": int(i.get("updatedAt", 0))} for i in items]})


def get_chat(user, chat_id):
    sessions, msgs = tables()
    if not get_session(sessions, user["sub"], chat_id):
        raise HttpError(404, "Chat not found.")
    return reply(200, {"chatId": chat_id, "messages": load_messages(msgs, user["sub"], chat_id, 200)})


def delete_chat(user, chat_id):
    sessions, msgs = tables()
    if not get_session(sessions, user["sub"], chat_id):
        raise HttpError(404, "Chat not found.")
    res = msgs.query(KeyConditionExpression=Key("pk").eq(f"USER#{user['sub']}") & Key("sk").begins_with(f"CHAT#{chat_id}#MSG#"))
    with msgs.batch_writer() as bw:
        for i in res.get("Items", []):
            bw.delete_item(Key={"pk": i["pk"], "sk": i["sk"]})
    sessions.delete_item(Key={"pk": f"USER#{user['sub']}", "sk": f"CHAT#{chat_id}"})
    return reply(200, {"deleted": chat_id})


@handler
def lambda_handler(event, context):
    user = user_from_event(event)
    route = event.get("routeKey", "")
    cid = (event.get("pathParameters") or {}).get("chatId")
    if route == "POST /chat":
        return chat(event, user)
    if route == "GET /chats":
        return list_chats(user)
    if route == "GET /chats/{chatId}":
        return get_chat(user, cid)
    if route == "DELETE /chats/{chatId}":
        return delete_chat(user, cid)
    raise HttpError(404, "Not found.")
