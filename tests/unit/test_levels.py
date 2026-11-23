import json
from types import SimpleNamespace as NS

import pytest
from botocore.exceptions import ClientError

from shared.common import HttpError, normalize_messages, user_from_event
from level3_chat import handler as l3
from level4_rag.handler import answer_with_rag, build_prompt
from level5_agent import tools
from level5_agent.handler import agent_turn
from level6_scale import jobs
from level7_platform import handler as l7, policy, router


# ---------- L2 / common ----------
def test_normalize_merges_and_drops_leading_assistant():
    out = normalize_messages([{"role": "assistant", "content": "hi"}, {"role": "user", "content": "a"},
                              {"role": "user", "content": "b"}])
    assert out == [{"role": "user", "content": "a\n\nb"}]


def test_normalize_requires_last_user():
    with pytest.raises(HttpError):
        normalize_messages([{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}])


def test_normalize_ignores_junk_roles_and_long_text():
    with pytest.raises(HttpError):
        normalize_messages([{"role": "system", "content": "x"}, {"role": "user", "content": "y" * 5000}])


def test_identity_only_from_jwt():
    with pytest.raises(HttpError) as e:
        user_from_event({"body": json.dumps({"sub": "attacker"})})
    assert e.value.status == 401


# ---------- L3 ----------
class Msgs:
    def __init__(self): self.kwargs = None
    def query(self, **kw):
        self.kwargs = kw   # newest first, as DynamoDB returns with ScanIndexForward=False
        return {"Items": [{"role": "user", "content": "new", "createdAt": 2}, {"role": "assistant", "content": "old", "createdAt": 1}]}


def test_load_messages_newest_limit_then_oldest_first():
    m = Msgs()
    out = l3.load_messages(m, "u1", "c1")
    assert m.kwargs["ScanIndexForward"] is False
    assert [x["content"] for x in out] == ["old", "new"]


# ---------- L4 ----------
class Store:
    def search(self, q, tenant_id, top_k=5):
        self.tenant = tenant_id
        return [{"n": 1, "text": "Refunds take 5 days.", "source": "s3://b/policy.pdf", "score": .9}]


class Prov:
    def __init__(self, outs): self.outs, self.calls = list(outs), []
    def generate(self, messages, **kw):
        self.calls.append((messages, kw))
        return self.outs.pop(0)


def test_rag_uses_tenant_and_returns_sources():
    s, p = Store(), Prov([{"text": "5 days [1]"}])
    res = answer_with_rag("refund time?", "acme", store=s, provider=p)
    assert s.tenant == "acme" and res["sources"][0]["source"].endswith("policy.pdf")
    assert "EXCERPTS" in build_prompt("q", s.search("q", "x"))


def test_rag_no_passages_skips_llm():
    class Empty:
        def search(self, *a, **k): return []
    assert "could not find" in answer_with_rag("q", "t", store=Empty(), provider=Prov([]))["answer"]


# ---------- L5 ----------
def test_tool_allowlist_and_schema():
    with pytest.raises(tools.ToolError):
        tools.validate_call("delete_database", {})
    with pytest.raises(tools.ToolError):
        tools.validate_call("lookup_order", {"order_id": "1", "customer_id": "other"})   # extra arg rejected
    tools.validate_call("lookup_order", {"order_id": "1"})


def test_agent_loop_queues_write_and_runs_read():
    use = lambda i, n, a: NS(type="tool_use", id=i, name=n, input=a)
    p = Prov([{"stop_reason": "tool_use", "content": [use("t1", "lookup_order", {"order_id": "9"}),
                                                       use("t2", "create_support_ticket", {"subject": "s", "details": "d"})]},
              {"stop_reason": "end_turn", "text": "Done", "content": []}])
    queued = []
    res = agent_turn("hi", {"sub": "u1"}, provider=p,
                     run_read=lambda n, a, u: {"order": a["order_id"], "owner": u["sub"]},
                     queue_write=lambda n, a, u: queued.append(n) or "act1")
    assert res["pendingActions"][0]["actionId"] == "act1" and queued == ["create_support_ticket"]
    results = p.calls[1][0][-1]["content"]
    assert len(results) == 2 and "act1" in results[1]["content"]


def test_agent_loop_is_bounded():
    use = NS(type="tool_use", id="t", name="list_orders", input={})
    p = Prov([{"stop_reason": "tool_use", "content": [use]}] * 10)
    with pytest.raises(HttpError):
        agent_turn("x", {"sub": "u"}, provider=p, run_read=lambda *a: [], queue_write=None)


# ---------- L6 ----------
class JobTable:
    def __init__(self): self.items = {}
    def put_item(self, Item, ConditionExpression=None):
        k = (Item["pk"], Item["sk"])
        if k in self.items:
            raise ClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, "PutItem")
        self.items[k] = Item


class Sqs:
    def __init__(self): self.sent = []
    def send_message(self, **kw): self.sent.append(kw)


def test_job_idempotency_key_prevents_duplicates(monkeypatch):
    monkeypatch.setenv("QUEUE_URL", "q")
    t, q = JobTable(), Sqs()
    ev = {"body": json.dumps({"text": "long"}), "headers": {"Idempotency-Key": "abc"}}
    a = jobs.create_job(ev, {"sub": "u"}, t, q)
    b = jobs.create_job(ev, {"sub": "u"}, t, q)
    assert a["statusCode"] == 202 and json.loads(b["body"])["status"] == "DUPLICATE" and len(q.sent) == 1


# ---------- L7 ----------
def test_dlp_detects_secrets_not_random_numbers():
    assert "aws_access_key" in policy.dlp_findings("key AKIAABCDEFGHIJKLMNOP")
    assert "card_number" in policy.dlp_findings("card 4111 1111 1111 1111")
    assert policy.dlp_findings("order 1234 5678 9012 3456") == []        # fails Luhn


def test_router_falls_back():
    def factory(spec):
        if spec == "anthropic:a":
            return NS(generate=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
        return NS(generate=lambda *a, **k: {"text": "ok", "provider": "bedrock", "model": "b"})
    out = router.generate_with_fallback(["anthropic:a", "bedrock:b"], [], "s", 10, factory=factory)
    assert out["provider"] == "bedrock"


class Tbl:
    def __init__(self, items=None): self.items, self.writes = items or {}, []
    def get_item(self, Key): return {"Item": self.items.get(Key["pk"])}
    def update_item(self, **kw): self.writes.append(kw)
    def put_item(self, Item): self.writes.append(Item)


def _platform(cfg_by_tenant):
    return l7.Platform(Tbl({f"TENANT#{k}": {"config": v} for k, v in cfg_by_tenant.items()}), Tbl(), Tbl())


def test_tenant_isolation_and_audit_keys():
    cfgs = {"A": {"routes": {"default": {"primary": "anthropic:m"}}}}
    p = _platform(cfgs)
    factory = lambda spec: NS(generate=lambda *a, **k: {"text": "hi", "provider": "anthropic", "model": "m",
                                                          "input_tokens": 5, "output_tokens": 5})
    ev = {"body": json.dumps({"message": "hello"})}
    res = l7.handle(ev, {"sub": "u", "tenant_id": "A"}, p, factory)
    assert res["statusCode"] == 200
    assert all(w["pk"].startswith("TENANT#A") for w in p.audit.writes)
    assert all(w["Key"]["pk"].startswith("TENANT#A#") for w in p.usage.writes)
    with pytest.raises(HttpError) as e:                                   # unknown tenant B is refused
        l7.handle(ev, {"sub": "u", "tenant_id": "B"}, p, factory)
    assert e.value.status == 403


def test_blocked_request_is_audited_without_content():
    p = _platform({"A": {"routes": {"default": {"primary": "anthropic:m"}}}})
    ev = {"body": json.dumps({"message": "my key AKIAABCDEFGHIJKLMNOP"})}
    with pytest.raises(HttpError) as e:
        l7.handle(ev, {"sub": "u", "tenant_id": "A"}, p)
    assert e.value.status == 422
    rec = p.audit.writes[0]
    assert rec["event"] == "blocked" and "AKIA" not in json.dumps(rec)
