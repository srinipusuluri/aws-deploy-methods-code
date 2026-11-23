"""Level 4: upload documents WITH tenant metadata so retrieval can filter by tenant.
Usage: python upload_docs.py <bucket> <tenant-id> <file> [file...]
Writes <file> and <file>.metadata.json ({"metadataAttributes": {"tenant_id": ...}}) under docs/<tenant>/."""
import json, os, sys, boto3
bucket, tenant, files = sys.argv[1], sys.argv[2], sys.argv[3:]
s3 = boto3.client("s3")
for f in files:
    key = f"docs/{tenant}/{os.path.basename(f)}"
    s3.upload_file(f, bucket, key)
    s3.put_object(Bucket=bucket, Key=key + ".metadata.json",
                  Body=json.dumps({"metadataAttributes": {"tenant_id": tenant}}).encode())
    print("uploaded", key)
print("Now run a Knowledge Base data source sync.")
