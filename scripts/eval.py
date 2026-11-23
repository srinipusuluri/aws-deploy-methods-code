"""Level 7 evaluation gate. Sends data/golden.jsonl to a deployed endpoint and checks expected phrases.
Usage: python eval.py <api-url> <id-token> [min-pass-rate=0.9]   (exit code 1 = gate failed)"""
import json, sys, urllib.request
api, token = sys.argv[1], sys.argv[2]
need = float(sys.argv[3]) if len(sys.argv) > 3 else 0.9
rows = [json.loads(l) for l in open(__file__.replace("scripts/eval.py", "data/golden.jsonl")) if l.strip()]
ok = 0
for r in rows:
    req = urllib.request.Request(api + "/v1/chat", json.dumps({"message": r["question"]}).encode(),
                                 {"Content-Type": "application/json", "Authorization": "Bearer " + token})
    try:
        ans = json.load(urllib.request.urlopen(req, timeout=30)).get("answer", "")
    except Exception as e:
        ans = ""; print("ERR", r["question"], e)
    hit = all(p.lower() in ans.lower() for p in r.get("must_contain", [])) and not any(p.lower() in ans.lower() for p in r.get("must_not_contain", []))
    ok += hit; print("PASS" if hit else "FAIL", "-", r["question"])
rate = ok / len(rows); print(f"pass rate {rate:.0%} (need {need:.0%})"); sys.exit(0 if rate >= need else 1)
