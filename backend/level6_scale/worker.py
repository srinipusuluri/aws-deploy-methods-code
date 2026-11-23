"""Level 6 - SQS worker. Partial-batch failures go back to the queue, then to the DLQ."""
import json, os

import boto3

from shared.common import log
from shared.providers import ClaudeProvider

SYSTEM = "Summarize the text for a busy reader in 5 bullet points."


def process(record, table, provider):
    msg = json.loads(record["body"])
    key = {"pk": f"USER#{msg['sub']}", "sk": f"JOB#{msg['jobId']}"}
    item = table.get_item(Key=key).get("Item")
    if not item or item["status"] == "DONE":      # idempotent: SQS is at-least-once
        return
    table.update_item(Key=key, UpdateExpression="SET #s = :s", ExpressionAttributeNames={"#s": "status"},
                      ExpressionAttributeValues={":s": "RUNNING"})
    out = provider.generate([{"role": "user", "content": item["text"]}], system=SYSTEM, max_tokens=800)
    table.update_item(Key=key, UpdateExpression="SET #s = :s, #r = :r",
                      ExpressionAttributeNames={"#s": "status", "#r": "result"},
                      ExpressionAttributeValues={":s": "DONE", ":r": out["text"]})


def lambda_handler(event, context):
    table = boto3.resource("dynamodb").Table(os.environ["JOBS_TABLE"])
    provider = ClaudeProvider(timeout=100.0, max_retries=2)     # SDK retries with backoff; no extra wrapper
    failures = []
    for rec in event["Records"]:
        try:
            process(rec, table, provider)
        except Exception:
            log.exception("job failed message_id=%s", rec["messageId"])
            failures.append({"itemIdentifier": rec["messageId"]})
    return {"batchItemFailures": failures}
