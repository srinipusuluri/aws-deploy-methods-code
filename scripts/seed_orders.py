"""Level 5 demo data. Usage: python seed_orders.py <orders-table> <cognito-sub>
Find the sub in Cognito > Users > your user."""
import sys, boto3
t = boto3.resource("dynamodb").Table(sys.argv[1])
for oid, item, status in [("1001", "Mechanical keyboard", "SHIPPED"), ("1002", "USB-C dock", "PROCESSING"), ("1003", "Monitor arm", "DELIVERED")]:
    t.put_item(Item={"customer_id": sys.argv[2], "order_id": oid, "item": item, "status": status})
print("seeded 3 orders")
