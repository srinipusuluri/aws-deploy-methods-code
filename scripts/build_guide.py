"""Builds docs/deployment-guide.html (build, deploy and Claude-in-Chrome manual steps per level)."""
import html, os

PRE = ("You are helping me with AWS console setup. Rules: (1) If a sign-in, MFA or CAPTCHA appears, stop and tell me; I will do it. "
       "(2) Never read, copy, type or repeat secret values (API keys, passwords, tokens) - when a secret must be entered, stop and let me type it. "
       "(3) Before any Create / Save / Delete / Deploy click, tell me exactly what you are about to change and wait for my OK. "
       "(4) Work only in region <REGION> and only on resources whose names start with <STACK>. "
       "(5) If a page does not match these instructions or a button is missing, stop and describe what you see instead of guessing.")

# step = (who, title, detail, prompt or None, expected)
COMMON = [
 ("You", "Create your Anthropic API key", "Do this yourself so the key never passes through an assistant.",
  "Open https://console.anthropic.com/settings/keys and stop there. Do not create the key or read any key value. I will create it myself.",
  "You hold a new key (shown once). Also set a monthly spend limit in the Anthropic console."),
 ("Claude in Chrome", "Store the key in AWS Secrets Manager", "Secret name claude-chatbot/anthropic, one key named api_key.",
  "Open https://<REGION>.console.aws.amazon.com/secretsmanager/newsecret. Choose 'Other type of secret' and 'Key/value'. Enter the key name api_key (exactly) and then STOP so I can paste the value myself. After I say continue: click Next, set the secret name to claude-chatbot/anthropic, leave rotation off, review, and Store. When saved, open the secret and tell me its ARN (the ARN is not secret).",
  "Secret exists; you have its ARN (arn:aws:secretsmanager:...:secret:claude-chatbot/anthropic-XXXXXX)."),
 ("Claude in Chrome", "Create a cost budget with email alerts", "Prevents surprise bills while testing.",
  "Open https://console.aws.amazon.com/costmanagement/home#/budgets/create. Choose 'Use a template' > 'Monthly cost budget', name it claude-chatbot-budget, set the amount I give you next (ask me), enter my email for alerts, then review. Wait for my OK before the final Create budget click.",
  "Budget exists with alerts at 85% actual / 100% forecast."),
 ("CLI", "Find your tested model ID and deploy", "Use a current Anthropic model ID from the Anthropic docs; it is a deploy parameter, not hard-coded.",
  None, "Deploy command shown in each level below."),
]
FRONT = [
 ("CLI", "Deploy the website stack", "Private S3 + CloudFront. Optional: serve the API at /api so one WAF protects both.",
  None, "SiteUrl output. Copy frontend/ to the bucket and invalidate CloudFront."),
 ("Claude in Chrome", "Verify the site and API origin", "Confirms CloudFront serves the site and routes /api.",
  "Open the CloudFront console at https://console.aws.amazon.com/cloudfront/v4/home, find the distribution whose domain I give you, and report: status (Deployed or In progress), the origins list, and the behaviors list. Do not change anything.",
  "Status Deployed; origins: site (S3, OAC) and, if used, api; behavior /api/* present."),
]
LEVELS = [
 dict(id="l1", n="1-2", title="Level 1-2: Basic Q&A and multi-turn", folder="backend/level1_basic, backend/level2_conversation", tpl="level1-2.yaml",
  cmd="scripts/deploy.sh 1-2 chatbot-l1 AnthropicSecretArn=<SECRET_ARN> ClaudeModel=<MODEL_ID> AllowedOrigin=https://<SITE_DOMAIN> Level=1",
  built="POST /chat. Level=1 takes {question}; Level=2 takes {messages} (validated, merged, last 12 turns). Throttled HTTP API, CORS locked to your origin, Secrets Manager key, 25 s timeout.",
  front="Set LEVEL to 1 or 2 and API_URL in frontend/config.js.",
  steps=[
  ("Claude in Chrome","Check the API route, CORS and throttling","Confirms the settings that protect a public endpoint.",
   "Open the API Gateway console at https://<REGION>.console.aws.amazon.com/apigateway. Open the HTTP API named like <STACK>-Api. Report: (a) the routes, (b) CORS configuration - allowed origins must be exactly https://<SITE_DOMAIN>, (c) stage throttling limits. Do not change anything; tell me if CORS shows '*'.",
   "One route POST /chat; one allowed origin; burst 20 / rate 10."),
  ("Claude in Chrome","Test the Lambda from the console","Proves the secret, model ID and code work before the browser is involved.",
   "Open the Lambda console, find the function named like <STACK>-ChatFn, open the Test tab, create an event named hello with this JSON: {\"body\": \"{\\\"question\\\": \\\"Say hi in five words\\\"}\"}. Ask me before running Test (it calls the paid API). After my OK run it and report the response status and body.",
   "statusCode 200 with an answer. If 500, open Monitor > View CloudWatch logs and report the last error line (not any message text)."),
  ("Claude in Chrome","Set log retention","Avoid logs growing forever.",
   "Open CloudWatch > Log groups, find /aws/lambda/<STACK>-ChatFn, and set retention to 30 days. Wait for my OK before saving.",
   "Retention 30 days.")]),
 dict(id="l3", n="3", title="Level 3: Login and saved chats", folder="backend/level3_chat", tpl="level3.yaml",
  cmd="scripts/deploy.sh 3 chatbot-l3 AnthropicSecretArn=<SECRET_ARN> ClaudeModel=<MODEL_ID> AllowedOrigin=https://<SITE_DOMAIN> CallbackUrl=https://<SITE_DOMAIN>/ CognitoDomainPrefix=<UNIQUE_PREFIX>",
  built="Cognito invite-only user pool with Hosted UI + PKCE, JWT-authorized HTTP API, DynamoDB sessions and messages. Every key derives from the token's sub; ownership is checked on read, update and delete.",
  front="Set LEVEL 3, API_URL, COGNITO_DOMAIN and COGNITO_CLIENT_ID from the stack outputs.",
  steps=[
  ("Claude in Chrome","Invite your first user","Users cannot self-register.",
   "Open Amazon Cognito > User pools > the pool named like <STACK>-UserPool > Users > Create user. Choose 'Send an email invitation', enter the email I give you (ask me), set custom:tenant_id to default if shown, and keep 'Mark email as verified' checked. Wait for my OK before Create user.",
   "User in status FORCE_CHANGE_PASSWORD; invite email sent."),
  ("Claude in Chrome","Verify the app client and Hosted UI","Callback URL must match the site exactly or login fails with redirect_mismatch.",
   "In the same Cognito user pool open App integration. Report: the Cognito domain, and for the app client: allowed callback URLs, OAuth grant type (must be Authorization code), scopes, and whether a client secret exists (it must not). Do not change anything.",
   "Callback = https://<SITE_DOMAIN>/, grant = code, no client secret."),
  ("Claude in Chrome","Confirm the JWT authorizer","API Gateway rejects missing or invalid tokens before Lambda runs.",
   "Open the API Gateway console > the HTTP API > Authorization. Report the authorizer's issuer URL and audience, and which routes have it attached. All four routes must have it. Do not change anything.",
   "Issuer https://cognito-idp.<REGION>.amazonaws.com/<pool-id>, audience = app client id."),
  ("Claude in Chrome","Check table protection","History is user data: confirm encryption and recovery.",
   "Open DynamoDB > Tables. For tables named like <STACK>-SessionsTable and <STACK>-MessagesTable report: encryption, point-in-time recovery status, and billing mode. Do not change anything.",
   "PITR enabled, SSE on, on-demand."),
  ("You","Sign in and chat","End-to-end test.", None, "Open the site, sign in, chat; refresh and confirm the chat list and history persist. In a second account confirm you cannot open the first user's chat.")]),
 dict(id="l4", n="4", title="Level 4: RAG knowledge chatbot", folder="backend/level4_rag", tpl="level4.yaml",
  cmd="scripts/deploy.sh 4 chatbot-l4 AnthropicSecretArn=<SECRET_ARN> ClaudeModel=<MODEL_ID> AllowedOrigin=https://<SITE_DOMAIN> CallbackUrl=https://<SITE_DOMAIN>/ CognitoDomainPrefix=<UNIQUE_PREFIX> KnowledgeBaseId=pending",
  built="POST /ask. Retrieves from an Amazon Bedrock Knowledge Base with a tenant_id metadata filter applied inside the retrieve call, then asks Claude to answer only from the excerpts with [n] citations. Private encrypted document bucket.",
  front="Set LEVEL 4. Order matters: deploy with KnowledgeBaseId=pending, create the knowledge base, then redeploy with the real ID.",
  steps=[
  ("Claude in Chrome","Enable the embedding model","The knowledge base needs an embedding model (Anthropic offers none).",
   "Open the Amazon Bedrock console in <REGION>. Find 'Model access' (or the Model catalog) and make sure Amazon Titan Text Embeddings V2 is available/enabled for this account. If an access request or EULA is needed, tell me what it says and wait for my OK. Report the final status.",
   "Titan Text Embeddings V2 shows Access granted / Available."),
  ("CLI","Upload documents with tenant metadata","Metadata sidecar files are what the tenant filter matches on.",
   None, "python scripts/upload_docs.py <DocBucketName> default data/sample_policy.txt"),
  ("Claude in Chrome","Create the knowledge base","Managed chunking, embedding and vector index.",
   "Open Amazon Bedrock > Knowledge bases > Create knowledge base (with vector store). Name it chatbot-kb. Data source: Amazon S3, choose the bucket I give you (the DocBucket output), inclusion prefix docs/. Embeddings model: Titan Text Embeddings V2. Vector store: choose the quick-create option offered by the console. Before the final Create click, summarize all choices and wait for my OK (vector stores can bill continuously).",
   "Knowledge base status Ready. Note: creation is slow (minutes)."),
  ("Claude in Chrome","Sync the data source and test retrieval with a filter","Proves ingestion works and the tenant filter matches.",
   "In the chatbot-kb knowledge base select the S3 data source and click Sync; wait until it shows Available and report the counts of scanned, indexed and failed files. Then use 'Test knowledge base' (retrieval only) with the query 'How long do refunds take?'; if filters are offered, add the metadata filter tenant_id equals default. Report the top result text and source. Then copy the knowledge base ID and tell me it.",
   "Top result mentions 5 business days; 0 failed files; you have the KB ID."),
  ("CLI","Redeploy with the real knowledge base ID","Grants bedrock:Retrieve on exactly that KB.", None,
   "Same deploy command with KnowledgeBaseId=<KB_ID>."),
  ("You","Isolation check","Retrieval must never cross tenants.", None,
   "Create a second user with custom:tenant_id=other and ask the refund question: the answer should say it cannot find it.")]),
 dict(id="l5", n="5", title="Level 5: Tools and agents", folder="backend/level5_agent", tpl="level5.yaml",
  cmd="scripts/deploy.sh 5 chatbot-l5 AnthropicSecretArn=<SECRET_ARN> ClaudeModel=<MODEL_ID> AllowedOrigin=https://<SITE_DOMAIN> CallbackUrl=https://<SITE_DOMAIN>/ CognitoDomainPrefix=<UNIQUE_PREFIX>",
  built="POST /agent runs a bounded (4-step) tool loop. lookup_order and list_orders are read-only and keyed by the verified user. create_support_ticket is queued as PENDING and only runs after POST /agent/approve (idempotent, expires in 1 hour). Every tool use is audited. Arguments are validated against JSON schemas.",
  front="Set LEVEL 5. The UI shows an Approve button for each pending action.",
  steps=[
  ("Claude in Chrome","Find your user's sub","Orders are keyed by the Cognito sub.",
   "Open Cognito > User pools > the pool named like <STACK>-UserPool > Users, open the user whose email I give you, and tell me the 'User ID (sub)' value.",
   "A UUID."),
  ("Claude in Chrome","Add demo orders in DynamoDB","Alternative to scripts/seed_orders.py.",
   "Open DynamoDB > Tables > the table named like <STACK>-OrdersTable > Explore table items > Create item. Switch to JSON view and create an item {\"customer_id\": {\"S\": \"<SUB>\"}, \"order_id\": {\"S\": \"1001\"}, \"item\": {\"S\": \"Mechanical keyboard\"}, \"status\": {\"S\": \"SHIPPED\"}}. Use the sub I give you. Ask me before saving, then repeat for order_id 1002 (USB-C dock, PROCESSING).",
   "Two items visible in Explore items."),
  ("You","Test the agent","Ask: 'Where is order 1001?' then 'Open a ticket: my dock arrived damaged'. Click Approve.", None,
   "Answer cites the order status; the ticket request appears as a button and nothing is created until you approve."),
  ("Claude in Chrome","Review the audit trail","Every tool call should leave an event.",
   "Open DynamoDB > the table named like <STACK>-AgentTable > Explore items. Report how many items start with AUDIT# and list their 'event' values (tool_read, tool_write_queued, tool_write_executed) and any TICKET# items. Do not change anything.",
   "Events for each step, one OPEN ticket.")]),
 dict(id="l6", n="6", title="Level 6: Production scale", folder="backend/level6_scale (+ level3_chat with quota)", tpl="level6.yaml",
  cmd="scripts/deploy.sh 6 chatbot-l6 AnthropicSecretArn=<SECRET_ARN> ClaudeModel=<MODEL_ID> AllowedOrigin=https://<SITE_DOMAIN> CallbackUrl=https://<SITE_DOMAIN>/ CognitoDomainPrefix=<UNIQUE_PREFIX> AlertEmail=<YOU@EXAMPLE.COM> DailyLimit=100",
  built="Level 3 chat plus per-user daily quotas (atomic DynamoDB counter), reserved Lambda concurrency, API throttling, POST /jobs (202 + Idempotency-Key) with SQS, a worker with partial-batch failure reporting, a dead-letter queue (3 receives), CloudWatch alarms to SNS, and X-Ray tracing. The SDK handles retries; there is no second retry wrapper.",
  front="Deploy frontend.yaml with ApiDomain so CloudFront serves /api, then attach WAF to CloudFront (WAF cannot attach to HTTP APIs).",
  steps=[
  ("You","Confirm the alert subscription","SNS will not send until the email is confirmed.", None,
   "Open the 'AWS Notification - Subscription Confirmation' email and click Confirm subscription."),
  ("Claude in Chrome","Create the WAF web ACL for CloudFront","CloudFront-scoped WAF must be created in us-east-1 (Global).",
   "Open https://us-east-1.console.aws.amazon.com/wafv2/homev2/web-acls and choose scope 'Global (CloudFront)'. Create web ACL named chatbot-waf. Add managed rule groups: AWS-AWSManagedRulesCommonRuleSet and AWS-AWSManagedRulesKnownBadInputsRuleSet. Add a custom rate-based rule named rate-per-ip: 300 requests per 5 minutes per IP, action Block. Default action Allow. Do not associate resources here. Summarize and wait for my OK before the final Create. Then tell me the web ACL ARN.",
   "Web ACL exists; you have its ARN."),
  ("CLI","Deploy the site stack with WAF","Pass the ARN and API host.", None,
   "sam deploy -t infrastructure/frontend.yaml --stack-name chatbot-site --resolve-s3 --capabilities CAPABILITY_IAM --parameter-overrides ApiDomain=<API_ID>.execute-api.<REGION>.amazonaws.com WebAclArn=<WEB_ACL_ARN>. Then set API_URL to /api in config.js."),
  ("Claude in Chrome","Verify the alarms and the queue","Alarms are what wake you up.",
   "Open CloudWatch > Alarms. Report the state of every alarm whose name contains <STACK>; then open SQS and report, for the queues named like <STACK>-JobsQueue and <STACK>-JobsDlq: messages available, messages in flight, and the dead-letter settings (max receives must be 3). Do not change anything.",
   "Alarms OK or Insufficient data; DLQ empty."),
  ("Claude in Chrome","Create a one-page dashboard","Latency, errors, queue depth, quota rejections.",
   "Open CloudWatch > Dashboards > Create dashboard named chatbot-prod. Add line widgets for: Lambda Duration and Errors for the ChatFn and WorkerFn, API Gateway 4xx and 5xx and Latency, SQS ApproximateNumberOfMessagesVisible for the DLQ. Ask me before the final Save.",
   "Dashboard saved."),
  ("CLI","Load and abuse tests","Prove the controls work before real users do.", None,
   "Send 30 rapid requests and confirm 429s from throttling; set DailyLimit=2 and confirm the third chat returns 429 'Daily usage limit reached'; send the same /jobs request twice with one Idempotency-Key and confirm one SQS message.")]),
 dict(id="l7", n="7", title="Level 7: Governed enterprise platform", folder="backend/level7_platform", tpl="level7.yaml",
  cmd="scripts/deploy.sh 7 chatbot-l7 AnthropicSecretArn=<SECRET_ARN> ClaudeModel=<MODEL_ID> AllowedOrigin=https://<SITE_DOMAIN> CallbackUrl=https://<SITE_DOMAIN>/ CognitoDomainPrefix=<UNIQUE_PREFIX>",
  built="POST /v1/chat gateway: tenant from the verified token only, tenant must be onboarded, DLP and size policy (blocked requests are audited by hash, not content), atomic per-tenant daily token budget, model router with fallback (Anthropic primary, Bedrock fallback), versioned prompts, audit records, and an evaluation gate script (scripts/eval.py) for CI.",
  front="Set LEVEL 7.",
  steps=[
  ("CLI","Onboard a tenant","The gateway returns 403 for tenants that are not in the table.", None,
   "python scripts/seed_tenant.py <TenantsTable> default <MODEL_ID> [<BEDROCK_MODEL_ID>]"),
  ("Claude in Chrome","Enable the fallback model in Bedrock","Only needed if you configure a Bedrock fallback route.",
   "Open the Amazon Bedrock console in <REGION>, Model access / Model catalog, and tell me whether the model ID I give you is available to this account. If an access request form is needed, tell me what it asks and wait for my OK.",
   "Model available, or you chose to skip the fallback."),
  ("Claude in Chrome","Assign users to tenants","The tenant comes from custom:tenant_id, which users cannot edit.",
   "Open Cognito > the user pool > Users, open the user whose email I give you, Edit attributes, set custom:tenant_id to the tenant id I give you, and wait for my OK before Save. The user must sign out and in again for the token to change.",
   "Attribute saved."),
  ("Claude in Chrome","Save audit queries in CloudWatch Logs Insights","Operations teams need these during an incident.",
   "Open CloudWatch > Logs Insights, select the log group /aws/lambda/<STACK>-GatewayFn, and save two queries: 'errors' (filter @message like /ERROR|Traceback/ | sort @timestamp desc | limit 50) and 'latency' (stats avg(@duration), pct(@duration, 95) by bin(5m)). Ask me before each Save.",
   "Two saved queries."),
  ("Claude in Chrome","Set backups for governance tables","Audit and tenant data must be recoverable.",
   "Open AWS Backup > Backup plans > Create plan from a template (Daily-35day-retention). Assign resources by tag or by choosing the DynamoDB tables named like <STACK>-AuditTable and <STACK>-TenantsTable. Summarize and wait for my OK before creating.",
   "Plan active; first backup job scheduled."),
  ("CLI","Run the tests and the evaluation gate","Deployment gate for every prompt or model change.", None,
   "pytest -q (includes tenant-isolation and DLP tests), then python scripts/eval.py https://<API> <ID_TOKEN> 0.9. Do not release if it exits 1."),
  ("You","Game day","Practice before you need it.", None,
   "Block the primary model (set a wrong model in a test tenant) and confirm fallback; exhaust a tenant budget and confirm 429; send a fake AWS key and confirm 422 plus an audit record with no content.")]),
]

def esc(s): return html.escape(s, quote=True)
def card(i, st, lid):
    who, title, detail, prompt, expected = st
    cls = {"Claude in Chrome": "chrome", "You": "you", "CLI": "cli"}[who]
    p = ""
    if prompt:
        pid = f"{lid}-{i}"
        p = (f'<div class="ph"><span>Prompt for Claude in Chrome</span><button class="copy" data-t="{pid}">Copy</button></div>'
             f'<pre id="{pid}">{esc(prompt)}</pre>')
    return (f'<div class="step"><div class="sh"><span class="who {cls}">{esc(who)}</span><b>{esc(title)}</b></div>'
            f'<p class="d">{esc(detail)}</p>{p}<p class="exp"><b>Expected:</b> {esc(expected)}</p></div>')

tabs, secs = [], []
tabs.append('<button class="tab on" data-s="start">Start here</button>')
start = f"""<section id="start" class="sec on"><h2>Before you begin</h2>
<p>This repository builds all seven levels. Code lives in <code>backend/</code>, templates in <code>infrastructure/</code>, the website in <code>frontend/</code>. Anything that is not a code or CLI action is a manual step, written as a prompt you can give to <b>Claude in Chrome</b>.</p>
<div class="warn"><b>Safe use of browser automation.</b> Use a sandbox or dev AWS account and an IAM role with only the permissions you need. Keep the preamble below on every prompt. You sign in, complete MFA and paste secrets yourself. Read each summary before replying OK. The prompts are written to stop and ask before any change.</div>
<h3>Preamble to put before every prompt</h3><div class="ph"><span>Safety preamble</span><button class="copy" data-t="pre">Copy</button></div><pre id="pre">{esc(PRE)}</pre>
<p>Replace <code>&lt;REGION&gt;</code>, <code>&lt;STACK&gt;</code>, <code>&lt;SITE_DOMAIN&gt;</code> and other angle-bracket values with yours before copying.</p>
<h3>Tools you need</h3><ul><li>AWS CLI and SAM CLI, configured with a profile (<code>aws sts get-caller-identity</code> works)</li><li>Python 3.12+, Node optional. <code>pip install -r backend/requirements.txt pytest</code> then <code>pytest -q</code> (15 tests)</li><li>Chrome with the Claude in Chrome extension, signed in to AWS</li></ul>
<h3>Repository map</h3><pre>claude-chatbot/
  backend/shared/            common helpers + provider adapters (Anthropic, Bedrock)
  backend/level1_basic/ ... level7_platform/   one folder per level
  infrastructure/            level1-2 ... level7.yaml, frontend.yaml (generated by build_templates.py)
  frontend/                  index.html, app.js, auth.js (Cognito PKCE), config.js
  scripts/                   deploy.sh, create_user.sh, seed_*.py, upload_docs.py, eval.py
  tests/unit/                15 tests incl. tenant isolation, DLP, idempotency, approval flow
  docs/deployment-guide.html this page</pre>
<h3>One-time setup (all levels)</h3>{''.join(card(i,s,'c') for i,s in enumerate(COMMON))}
<h3>Website (all levels)</h3>{''.join(card(i,s,'f') for i,s in enumerate(FRONT))}
<pre id="fe">aws s3 sync frontend/ s3://&lt;SiteBucketName&gt;/ --delete
aws cloudfront create-invalidation --distribution-id &lt;DistributionId&gt; --paths "/*"</pre>
<p class="d">Status: templates pass cfn-lint, unit tests pass, the JavaScript parses. Nothing has been deployed to AWS from this machine, so treat the first deployment as a test. Check service names and console wording against the current AWS console; the prompts tell Claude to stop when the page differs.</p></section>"""
secs.append(start)
for L in LEVELS:
    tabs.append(f'<button class="tab" data-s="{L["id"]}">{esc("L"+L["n"])}</button>')
    secs.append(f"""<section id="{L['id']}" class="sec"><h2>{esc(L['title'])}</h2>
<p><b>Source:</b> <code>{esc(L['folder'])}</code> &nbsp; <b>Template:</b> <code>infrastructure/{L['tpl']}</code></p>
<p><b>What was built:</b> {esc(L['built'])}</p>
<h3>1. Deploy (CLI)</h3><div class="ph"><span>bash</span><button class="copy" data-t="{L['id']}-cmd">Copy</button></div><pre id="{L['id']}-cmd">{esc(L['cmd'])}</pre>
<p class="d">{esc(L['front'])}</p>
<h3>2. Manual steps</h3>{''.join(card(i,s,L['id']) for i,s in enumerate(L['steps']))}</section>""")
page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Claude Chatbot on AWS - Build and Claude in Chrome Guide</title><style>
:root{{--ink:#14213d;--mut:#61708a;--line:#dce4ef;--bg:#f4f7fb;--blue:#2563eb;--green:#0d9668;--amber:#b45309}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 system-ui,-apple-system,Segoe UI,sans-serif}}
header{{background:#10213e;color:#fff;padding:26px max(18px,calc((100vw - 1000px)/2))}}header h1{{margin:0 0 6px;font-size:26px}}header p{{margin:0;color:#c9d6ee}}
.bar{{position:sticky;top:0;background:#fff;border-bottom:1px solid var(--line);display:flex;gap:6px;padding:8px max(18px,calc((100vw - 1000px)/2));flex-wrap:wrap;z-index:5}}
.tab{{border:1px solid var(--line);background:#fff;border-radius:8px;padding:7px 14px;cursor:pointer;font:inherit}}.tab.on{{background:#eaf1ff;color:#1646a1;border-color:#9db9ee;font-weight:700}}
main{{max-width:1000px;margin:auto;padding:18px}}.sec{{display:none}}.sec.on{{display:block}}h2{{margin:6px 0 10px}}h3{{margin:22px 0 8px}}
code{{background:#e8eef8;padding:1px 5px;border-radius:4px;font-size:13px}}pre{{background:#0c1729;color:#e5edf9;padding:14px;border-radius:10px;overflow:auto;font:12.5px/1.55 ui-monospace,Menlo,monospace;white-space:pre-wrap;word-break:break-word;margin:0 0 8px}}
.ph{{display:flex;justify-content:space-between;align-items:center;font-size:12px;font-weight:700;color:var(--mut);margin:8px 0 4px}}
.copy{{border:1px solid #cbd5e1;background:#fff;border-radius:7px;padding:4px 10px;cursor:pointer;font-weight:700}}
.step{{background:#fff;border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin:10px 0}}.sh{{display:flex;gap:10px;align-items:center;flex-wrap:wrap}}
.who{{font-size:11px;font-weight:800;padding:3px 9px;border-radius:99px;color:#fff}}.chrome{{background:var(--blue)}}.you{{background:var(--amber)}}.cli{{background:var(--green)}}
.d{{color:var(--mut);margin:6px 0}}.exp{{margin:6px 0 0;font-size:13px}}.warn{{border-left:4px solid var(--amber);background:#fff7e9;padding:12px 14px;border-radius:0 9px 9px 0;margin:12px 0}}
@media(max-width:600px){{main{{padding:12px}}}}</style></head><body>
<header><h1>Claude Chatbot on AWS</h1><p>Build, deploy and verify all seven levels. Manual console steps are written as prompts for Claude in Chrome.</p></header>
<div class="bar">{''.join(tabs)}</div><main>{''.join(secs)}</main>
<script>
document.querySelectorAll('.tab').forEach(b=>b.onclick=()=>{{document.querySelectorAll('.tab,.sec').forEach(x=>x.classList.remove('on'));b.classList.add('on');document.getElementById(b.dataset.s).classList.add('on');scrollTo(0,0)}});
document.querySelectorAll('.copy').forEach(b=>b.onclick=async()=>{{const t=document.getElementById(b.dataset.t).innerText;try{{await navigator.clipboard.writeText(t);b.textContent='Copied'}}catch(e){{b.textContent='Select text'}}setTimeout(()=>b.textContent='Copy',1500)}});
</script></body></html>"""
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs", "deployment-guide.html")
open(out, "w").write(page); print("written", len(page))
