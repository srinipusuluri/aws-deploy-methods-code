"""Level 7: onboard a tenant. Usage: python seed_tenant.py <tenants-table> <tenant-id> <anthropic-model> [bedrock-model-id]"""
import sys, boto3
table, tenant, claude = sys.argv[1:4]
route = {"primary": f"anthropic:{claude}"}
if len(sys.argv) > 4:
    route["fallback"] = f"bedrock:{sys.argv[4]}"
boto3.resource("dynamodb").Table(table).put_item(Item={"pk": f"TENANT#{tenant}", "config": {
    "daily_tokens": 200000, "max_input_chars": 8000, "dlp": True, "prompt_version": "v2", "routes": {"default": route}}})
print("tenant", tenant, "onboarded")
