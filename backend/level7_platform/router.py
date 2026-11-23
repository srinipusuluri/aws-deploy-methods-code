"""Level 7 - model router with fallback. Routes come from tenant config, not from the caller."""
from shared.common import log
from shared.providers import get_provider


def route(tenant_cfg, use_case):
    routes = tenant_cfg.get("routes", {})
    r = routes.get(use_case) or routes.get("default") or {}
    primary = r.get("primary")
    if not primary:
        raise RuntimeError("No model route configured for tenant.")
    return [primary] + ([r["fallback"]] if r.get("fallback") else [])


def generate_with_fallback(specs, messages, system, max_tokens, factory=get_provider):
    last = None
    for spec in specs:
        try:
            return factory(spec).generate(messages, system=system, max_tokens=max_tokens)
        except Exception as e:                      # provider outage / throttling -> next route
            log.warning("provider failed spec=%s type=%s", spec, type(e).__name__)
            last = e
    raise last
