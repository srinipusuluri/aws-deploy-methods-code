"""Level 6 - async long jobs. API enqueues to SQS and returns 202; worker does the slow call.

POST /jobs   {text}  (+ optional Idempotency-Key header)  -> 202 {jobId}
GET  /jobs/{jobId}                                          -> status/result
(The interactive chat path is level3_chat with QUOTA_TABLE + DAILY_LIMIT set.)"""
import json, os, time, uuid

import boto3
from botocore.exceptions import ClientError

from shared.common import HttpError, check_quota, clean_text, handler, parse_json, reply, user_from_event

MAX_JOB_TEXT = 50000


def _res():
    return boto3.resource("dynamodb").Table(os.environ["JOBS_TABLE"]), boto3.client("sqs")


def create_job(event, user, table=None, sqs=None):
    if table is None:
        table, sqs = _res()
    text = clean_text(parse_json(event).get("text"), "text", MAX_JOB_TEXT)
    check_quota(f"USER#{user['sub']}")
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    # Same Idempotency-Key from the same user -> same job id, never a duplicate.
    key = headers.get("idempotency-key")
    job_id = uuid.uuid5(uuid.NAMESPACE_URL, f"{user['sub']}:{key}").hex if key else uuid.uuid4().hex
    try:
        table.put_item(Item={"pk": f"USER#{user['sub']}", "sk": f"JOB#{job_id}", "status": "QUEUED",
                             "text": text, "createdAt": int(time.time()), "expires": int(time.time()) + 7 * 86400},
                       ConditionExpression="attribute_not_exists(pk)")
    except ClientError as e:
        if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
        return reply(200, {"jobId": job_id, "status": "DUPLICATE"})
    sqs.send_message(QueueUrl=os.environ["QUEUE_URL"], MessageBody=json.dumps({"sub": user["sub"], "jobId": job_id}))
    return reply(202, {"jobId": job_id, "status": "QUEUED"})


def get_job(user, job_id, table=None):
    table = table or _res()[0]
    item = table.get_item(Key={"pk": f"USER#{user['sub']}", "sk": f"JOB#{job_id}"}).get("Item")
    if not item:
        raise HttpError(404, "Job not found.")
    return reply(200, {"jobId": job_id, "status": item["status"], "result": item.get("result"), "error": item.get("error")})


@handler
def lambda_handler(event, context):
    user = user_from_event(event)
    if event.get("routeKey") == "POST /jobs":
        return create_job(event, user)
    return get_job(user, (event.get("pathParameters") or {}).get("jobId"))
