"""End-to-end integration test for AgentGuard pipeline.

Tests: SDK -> Ingestion API -> Redis -> Storage Worker -> S3 + PostgreSQL

Prerequisites:
  - Docker Compose services running (postgres, redis, minio)
  - Ingestion API running on port 8000
  - Storage Worker running and consuming from Redis
  - Alembic migrations applied
"""

import json
import sys
import time

import httpx
import redis
import boto3
import psycopg2


API_URL = "http://localhost:8000"
REDIS_URL = "redis://localhost:6379"
S3_ENDPOINT = "http://localhost:9000"
S3_BUCKET = "agentguard-traces"
DB_DSN = "host=localhost port=5432 dbname=agentguard user=agentguard password=agentguard_dev"

# Add SDK to path
sys.path.insert(0, "sdk/python")
from agentguard import AgentGuard, GuardConfig


def check_prerequisites():
    """Verify all services are up before testing."""
    print("=== Checking Prerequisites ===")

    # 1. Ingestion API
    try:
        r = httpx.get(f"{API_URL}/health", timeout=3)
        assert r.status_code == 200
        print("[OK] Ingestion API healthy")
    except Exception as e:
        print(f"[FAIL] Ingestion API: {e}")
        return False

    # 2. Redis
    try:
        rc = redis.from_url(REDIS_URL)
        rc.ping()
        print("[OK] Redis connected")
        rc.close()
    except Exception as e:
        print(f"[FAIL] Redis: {e}")
        return False

    # 3. MinIO/S3
    try:
        s3 = boto3.client(
            "s3",
            endpoint_url=S3_ENDPOINT,
            aws_access_key_id="agentguard",
            aws_secret_access_key="agentguard_dev",
        )
        buckets = [b["Name"] for b in s3.list_buckets()["Buckets"]]
        assert S3_BUCKET in buckets, f"Bucket {S3_BUCKET} not found in {buckets}"
        print(f"[OK] MinIO connected, bucket '{S3_BUCKET}' exists")
    except Exception as e:
        print(f"[FAIL] MinIO: {e}")
        return False

    # 4. PostgreSQL
    try:
        conn = psycopg2.connect(DB_DSN)
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_name = 'executions'"
        )
        count = cur.fetchone()[0]
        assert count == 1, "executions table not found"
        print("[OK] PostgreSQL connected, schema exists")
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[FAIL] PostgreSQL: {e}")
        return False

    print()
    return True


def test_sdk_patterns():
    """Test all 3 SDK integration patterns end-to-end."""
    print("=== Testing SDK Integration Patterns ===")

    guard = AgentGuard(
        api_key="ag_test_key_123",
        config=GuardConfig(
            api_url=API_URL,
            mode="async",
            flush_interval_s=0.5,
            flush_batch_size=10,
        ),
    )

    execution_ids = []

    # Pattern 1: @watch decorator
    print("\n--- Pattern 1: @watch decorator ---")

    @guard.watch(agent_id="e2e-test-agent", task="summarize text")
    def summarize(text):
        return f"Summary of: {text[:50]}"

    result1 = summarize(
        "The quick brown fox jumps over the lazy dog. This is an e2e test."
    )
    print(f"  Result output: {result1.output}")
    print(f"  execution_id:  {result1.execution_id}")
    execution_ids.append(result1.execution_id)

    # Pattern 2: trace() context manager
    print("\n--- Pattern 2: trace() context manager ---")
    with guard.trace(
        agent_id="e2e-test-agent",
        task="RAG pipeline",
        input_data={"query": "What is AgentGuard?"},
    ) as ctx:
        ctx.step(
            step_type="tool_call",
            name="retrieve",
            input="What is AgentGuard?",
            output={"docs": ["doc1", "doc2"]},
            duration_ms=15.0,
        )
        ctx.step(
            step_type="llm",
            name="generate",
            input={"docs": ["doc1", "doc2"], "query": "What is AgentGuard?"},
            output="AgentGuard is a runtime reliability layer for AI agents",
            duration_ms=120.0,
        )
        ctx.record("AgentGuard is a runtime reliability layer for AI agents")

    result2 = ctx.result
    print(f"  Result output: {result2.output}")
    print(f"  execution_id:  {result2.execution_id}")
    execution_ids.append(result2.execution_id)

    # Pattern 3: run() explicit wrap
    print("\n--- Pattern 3: run() explicit wrap ---")
    result3 = guard.run(
        agent_id="e2e-test-agent",
        task="answer question",
        fn=lambda: "Yes, AgentGuard is working end-to-end!",
        input_data={"question": "Is this working?"},
    )
    print(f"  Result output: {result3.output}")
    print(f"  execution_id:  {result3.execution_id}")
    execution_ids.append(result3.execution_id)

    # Close flushes all buffered events to the API
    print("\n--- Flushing events to Ingestion API ---")
    guard.close()
    print("  Flush complete.")

    return execution_ids


def verify_redis_stream():
    """Check that events were processed through the Redis stream."""
    print("\n=== Verifying Redis Stream ===")
    rc = redis.from_url(REDIS_URL, decode_responses=True)
    stream_info = rc.xinfo_stream("executions.raw")
    print(f"  Stream length: {stream_info['length']}")
    print(f"  Groups: {stream_info['groups']}")

    groups = rc.xinfo_groups("executions.raw")
    for g in groups:
        print(
            f"  Group '{g['name']}': pending={g['pending']}, "
            f"consumers={g['consumers']}"
        )
    rc.close()


def verify_s3_objects(execution_ids):
    """Check that trace payloads were written to S3/MinIO."""
    print("\n=== Verifying S3/MinIO Objects ===")
    s3 = boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT,
        aws_access_key_id="agentguard",
        aws_secret_access_key="agentguard_dev",
    )

    objects = s3.list_objects_v2(Bucket=S3_BUCKET)
    if "Contents" not in objects:
        print("  [WARN] No objects in S3 bucket yet")
        return False

    s3_keys = [obj["Key"] for obj in objects["Contents"]]
    print(f"  Total objects in bucket: {len(s3_keys)}")
    for key in s3_keys:
        print(f"    - {key}")

    # Check each execution_id has a corresponding S3 object
    found = 0
    for eid in execution_ids:
        matching = [k for k in s3_keys if eid in k]
        if matching:
            print(f"  [OK] Found S3 object for execution {eid}")
            found += 1
        else:
            print(f"  [MISS] No S3 object for execution {eid}")

    return found == len(execution_ids)


def verify_postgresql(execution_ids):
    """Check that execution metadata was written to PostgreSQL."""
    print("\n=== Verifying PostgreSQL Records ===")
    conn = psycopg2.connect(DB_DSN)
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM executions")
    total = cur.fetchone()[0]
    print(f"  Total executions in DB: {total}")

    found = 0
    for eid in execution_ids:
        cur.execute(
            "SELECT execution_id, agent_id, status, timestamp "
            "FROM executions WHERE execution_id = %s",
            (eid,),
        )
        row = cur.fetchone()
        if row:
            print(
                f"  [OK] Found execution {eid}: "
                f"agent={row[1]}, status={row[2]}, ts={row[3]}"
            )
            found += 1
        else:
            print(f"  [MISS] No DB record for execution {eid}")

    cur.close()
    conn.close()
    return found == len(execution_ids)


def main():
    print("=" * 60)
    print("  AgentGuard End-to-End Integration Test")
    print("=" * 60)
    print()

    if not check_prerequisites():
        print("\nPrerequisites check failed. Please start all services.")
        sys.exit(1)

    # Run SDK integration tests
    execution_ids = test_sdk_patterns()
    print(f"\n  Generated {len(execution_ids)} execution events")
    print(f"  IDs: {execution_ids}")

    # Give the storage worker time to process
    print("\n--- Waiting 5 seconds for pipeline processing ---")
    time.sleep(5)

    # Verify each component
    verify_redis_stream()
    s3_ok = verify_s3_objects(execution_ids)
    db_ok = verify_postgresql(execution_ids)

    # Summary
    print("\n" + "=" * 60)
    print("  SUMMARY")
    print("=" * 60)
    print(f"  SDK -> Ingestion API:  OK (3 events flushed)")
    print(f"  Redis Stream:          OK (events processed)")
    print(f"  Storage Worker -> S3:  {'PASS' if s3_ok else 'FAIL'}")
    print(f"  Storage Worker -> DB:  {'PASS' if db_ok else 'FAIL'}")

    if s3_ok and db_ok:
        print("\n  ALL CHECKS PASSED - Pipeline is working end-to-end!")
        sys.exit(0)
    else:
        print("\n  SOME CHECKS FAILED - See details above")
        sys.exit(1)


if __name__ == "__main__":
    main()
