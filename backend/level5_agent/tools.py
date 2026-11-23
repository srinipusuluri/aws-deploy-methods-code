"""Level 5 tools. Allowlist + schema validation + authorization in the data layer.
Read tools run immediately. Write tools are queued for explicit human approval."""
import os, time, uuid

import boto3
from jsonschema import ValidationError, validate

READ_TOOLS = {
    "lookup_order": {
        "name": "lookup_order",
        "description": "Look up one order that belongs to the signed-in customer.",
        "input_schema": {"type": "object", "properties": {"order_id": {"type": "string", "maxLength": 40}},
                         "required": ["order_id"], "additionalProperties": False}},
    "list_orders": {
        "name": "list_orders",
        "description": "List the signed-in customer's most recent orders.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False}},
}
WRITE_TOOLS = {
    "create_support_ticket": {
        "name": "create_support_ticket",
        "description": "Open a support ticket for the signed-in customer. Requires the customer's approval.",
        "input_schema": {"type": "object",
                         "properties": {"subject": {"type": "string", "maxLength": 120},
                                        "details": {"type": "string", "maxLength": 1000}},
                         "required": ["subject", "details"], "additionalProperties": False}},
}
TOOL_DEFS = [*READ_TOOLS.values(), *WRITE_TOOLS.values()]
ALL = {**READ_TOOLS, **WRITE_TOOLS}


class ToolError(Exception):
    pass


def _tables():
    r = boto3.resource("dynamodb")
    return r.Table(os.environ["ORDERS_TABLE"]), r.Table(os.environ["AGENT_TABLE"])


def validate_call(name, args):
    if name not in ALL:
        raise ToolError("Tool not allowed.")
    try:
        validate(args, ALL[name]["input_schema"])
    except ValidationError as e:
        raise ToolError(f"Invalid arguments: {e.message}")


def audit(table, user, event, **fields):
    table.put_item(Item={"pk": f"USER#{user['sub']}", "sk": f"AUDIT#{int(time.time()*1000):013d}#{uuid.uuid4().hex[:6]}",
                         "event": event, "expires": int(time.time()) + 365 * 86400, **fields})


def run_read_tool(name, args, user, orders=None, agent=None):
    orders, agent = (orders, agent) if orders is not None else _tables()
    validate_call(name, args)
    cust = user["sub"]                       # authorization: key is derived from the verified identity
    if name == "lookup_order":
        item = orders.get_item(Key={"customer_id": cust, "order_id": args["order_id"]}).get("Item")
        result = item or {"error": "No such order for this customer."}
    else:
        from boto3.dynamodb.conditions import Key
        result = orders.query(KeyConditionExpression=Key("customer_id").eq(cust), Limit=10).get("Items", [])
    audit(agent, user, "tool_read", tool=name)
    return result


def queue_write_tool(name, args, user, agent=None):
    agent = agent if agent is not None else _tables()[1]
    validate_call(name, args)
    action_id = uuid.uuid4().hex
    agent.put_item(Item={"pk": f"USER#{user['sub']}", "sk": f"ACTION#{action_id}", "tool": name, "args": args,
                         "status": "PENDING", "expires": int(time.time()) + 3600})
    audit(agent, user, "tool_write_queued", tool=name, actionId=action_id)
    return action_id


def approve_action(action_id, user, agent=None):
    """Idempotent: PENDING -> EXECUTED can only happen once."""
    from botocore.exceptions import ClientError
    agent = agent if agent is not None else _tables()[1]
    key = {"pk": f"USER#{user['sub']}", "sk": f"ACTION#{action_id}"}
    try:
        item = agent.update_item(Key=key, UpdateExpression="SET #s = :e",
                                 ConditionExpression="#s = :p AND expires > :now",
                                 ExpressionAttributeNames={"#s": "status"},
                                 ExpressionAttributeValues={":e": "EXECUTED", ":p": "PENDING", ":now": int(time.time())},
                                 ReturnValues="ALL_NEW")["Attributes"]
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            raise ToolError("Action is not pending (already handled or expired).")
        raise
    ticket_id = uuid.uuid4().hex[:10]
    agent.put_item(Item={"pk": f"USER#{user['sub']}", "sk": f"TICKET#{ticket_id}", **item["args"], "status": "OPEN"})
    audit(agent, user, "tool_write_executed", tool=item["tool"], actionId=action_id, ticketId=ticket_id)
    return {"ticketId": ticket_id, "status": "OPEN"}
