"""Level 7 - governed AI gateway: tenant resolve -> policy/DLP -> budget -> route -> audit.

POST /v1/chat {messages|message, useCase?}   (JWT required; tenant comes from the token)"""
import hashlib, os, time, uuid

import boto3
from botocore.exceptions import ClientError

from shared.common import HttpError, clean_text, handler, normalize_messages, parse_json, reply, today, user_from_event
from level7_platform import policy, router
from level7_platform.prompts import DEFAULT_VERSION, PROMPTS

DEFAULT_CFG = {"max_input_chars": 8000, "dlp": True, "daily_tokens": 200000,
               "routes": {"default": {"primary": "anthropic:" + os.environ.get("CLAUDE_MODEL", "")}}}


class Platform:
    def __init__(self, tenants=None, usage=None, audit=None):
        r = boto3.resource("dynamodb") if tenants is None else None
        self.tenants = tenants if tenants is not None else r.Table(os.environ["TENANTS_TABLE"])
        self.usage = usage if usage is not None else r.Table(os.environ["USAGE_TABLE"])
        self.audit = audit if audit is not None else r.Table(os.environ["AUDIT_TABLE"])

    def tenant_cfg(self, tenant_id):
        item = self.tenants.get_item(Key={"pk": f"TENANT#{tenant_id}"}).get("Item")
        if not item:
            if os.environ.get("ALLOW_UNREGISTERED_TENANTS") == "true":
                return DEFAULT_CFG
            raise HttpError(403, "Tenant is not onboarded.")
        return {**DEFAULT_CFG, **item.get("config", {})}

    def reserve_tokens(self, tenant_id, budget, est):
        """Atomic per-tenant daily budget; keys always include the tenant id."""
        try:
            self.usage.update_item(
                Key={"pk": f"TENANT#{tenant_id}#DAY#{today()}"},
                UpdateExpression="ADD tokens :t SET expires = :e",
                ConditionExpression="attribute_not_exists(tokens) OR tokens <= :max",
                ExpressionAttributeValues={":t": est, ":max": budget - est, ":e": int(time.time()) + 3 * 86400})
        except ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise HttpError(429, "Tenant daily token budget reached.")
            raise

    def record_usage(self, tenant_id, extra):
        if extra:
            self.usage.update_item(Key={"pk": f"TENANT#{tenant_id}#DAY#{today()}"},
                                   UpdateExpression="ADD tokens :t", ExpressionAttributeValues={":t": extra})

    def write_audit(self, tenant_id, user, **fields):
        self.audit.put_item(Item={"pk": f"TENANT#{tenant_id}", "sk": f"{int(time.time()*1000):013d}#{uuid.uuid4().hex[:6]}",
                                  "user": user["sub"], "expires": int(time.time()) + 365 * 86400, **fields})


def handle(event, user, platform=None, factory=None):
    p = platform or Platform()
    tenant = user["tenant_id"]
    cfg = p.tenant_cfg(tenant)
    body = parse_json(event)
    messages = normalize_messages(body["messages"] if "messages" in body
                                  else [{"role": "user", "content": clean_text(body.get("message"), "message")}])
    use_case = str(body.get("useCase", "default"))[:40]
    text_all = "\n".join(m["content"] for m in messages)
    prompt_hash = hashlib.sha256(text_all.encode()).hexdigest()[:16]     # hash, not the content
    decision, reasons = policy.evaluate(text_all, cfg)
    version = cfg.get("prompt_version", DEFAULT_VERSION)
    if decision == "block":
        p.write_audit(tenant, user, event="blocked", reasons=reasons, promptHash=prompt_hash, promptVersion=version)
        raise HttpError(422, "Request blocked by policy: " + ", ".join(reasons))
    est = len(text_all) // 3 + 800
    p.reserve_tokens(tenant, int(cfg["daily_tokens"]), est)
    kwargs = {"factory": factory} if factory else {}
    out = router.generate_with_fallback(router.route(cfg, use_case), messages, PROMPTS[version], 800, **kwargs)
    p.record_usage(tenant, out["input_tokens"] + out["output_tokens"] - est)
    p.write_audit(tenant, user, event="completion", provider=out["provider"], model=out["model"], useCase=use_case,
                  promptHash=prompt_hash, promptVersion=version,
                  tokensIn=out["input_tokens"], tokensOut=out["output_tokens"])
    return reply(200, {"answer": out["text"], "provider": out["provider"], "model": out["model"], "promptVersion": version})


@handler
def lambda_handler(event, context):
    return handle(event, user_from_event(event))
