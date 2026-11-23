"""Shared helpers for every level: responses, auth claims, secrets, quotas."""
import json, logging, os, time
from datetime import datetime, timezone

import boto3

log = logging.getLogger()
log.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

MAX_TEXT = 4000


class HttpError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status, self.message = status, message


def BadRequest(message):
    return HttpError(400, message)


def reply(status, body):
    # CORS headers come from the HTTP API / CloudFront, never from here.
    return {"statusCode": status,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(body, default=str)}


def parse_json(event):
    try:
        data = json.loads(event.get("body") or "{}")
    except ValueError:
        raise BadRequest("Body must be JSON.")
    if not isinstance(data, dict):
        raise BadRequest("Body must be a JSON object.")
    return data


def clean_text(value, field="text", limit=MAX_TEXT):
    if not isinstance(value, str) or not value.strip():
        raise BadRequest(f"{field} is required.")
    value = value.strip()
    if len(value) > limit:
        raise BadRequest(f"{field} must be at most {limit} characters.")
    return value


def user_from_event(event):
    """Identity comes ONLY from the JWT claims validated by API Gateway."""
    claims = (event.get("requestContext", {}).get("authorizer", {})
              .get("jwt", {}).get("claims", {}))
    sub = claims.get("sub")
    if not sub:
        raise HttpError(401, "Authentication required.")
    groups = claims.get("cognito:groups", "")
    return {"sub": sub, "email": claims.get("email"),
            "tenant_id": claims.get("custom:tenant_id") or os.environ.get("DEFAULT_TENANT", "default"),
            "groups": groups if isinstance(groups, list) else str(groups).strip("[]").replace(",", " ").split()}


def handler(fn):
    """Wrap a handler: map HttpError -> status, log unexpected errors without bodies."""
    def wrapped(event, context):
        try:
            return fn(event, context)
        except HttpError as e:
            return reply(e.status, {"error": e.message})
        except Exception:
            log.exception("request failed request_id=%s", getattr(context, "aws_request_id", "-"))
            return reply(500, {"error": "Sorry, the assistant is unavailable."})
    wrapped.__name__ = fn.__name__
    return wrapped


def normalize_messages(items, keep=12):
    """Validate untrusted history: roles, size, merge same-role neighbours, start with user."""
    if not isinstance(items, list):
        raise BadRequest("messages must be a list.")
    out = []
    for item in items[-keep:]:
        if not isinstance(item, dict):
            continue
        role, content = item.get("role"), item.get("content")
        if role not in ("user", "assistant") or not isinstance(content, str):
            continue
        content = content.strip()
        if not content or len(content) > MAX_TEXT:
            continue
        if out and out[-1]["role"] == role:
            out[-1]["content"] += "\n\n" + content
        else:
            out.append({"role": role, "content": content})
    while out and out[0]["role"] != "user":
        out.pop(0)
    if not out or out[-1]["role"] != "user":
        raise BadRequest("The last message must come from the user.")
    return out


# ---- secrets ---------------------------------------------------------------
_api_key = None


def anthropic_api_key():
    global _api_key
    if _api_key is None:
        sm = boto3.client("secretsmanager")
        secret = sm.get_secret_value(SecretId=os.environ["ANTHROPIC_SECRET_ARN"])
        _api_key = json.loads(secret["SecretString"])["api_key"]
    return _api_key


# ---- quotas ----------------------------------------------------------------
def today():
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def check_quota(subject, amount=1, limit=None, table=None):
    """Atomic per-day counter. Raises 429 when the daily limit would be exceeded.
    No-op when QUOTA_TABLE is not configured (levels 1-5)."""
    table = table or _quota_table()
    limit = limit if limit is not None else int(os.environ.get("DAILY_LIMIT", "0"))
    if table is None or limit <= 0:
        return
    from botocore.exceptions import ClientError
    try:
        table.update_item(
            Key={"pk": f"{subject}#DAY#{today()}"},
            UpdateExpression="ADD used :a SET expires = :e",
            ConditionExpression="attribute_not_exists(used) OR used <= :max",
            ExpressionAttributeValues={":a": amount, ":max": limit - amount,
                                       ":e": int(time.time()) + 3 * 86400})
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            raise HttpError(429, "Daily usage limit reached. Try again tomorrow.")
        raise


def _quota_table():
    name = os.environ.get("QUOTA_TABLE")
    return boto3.resource("dynamodb").Table(name) if name else None
