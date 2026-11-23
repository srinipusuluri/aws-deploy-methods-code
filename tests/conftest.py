import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("CLAUDE_MODEL", "test-model")
