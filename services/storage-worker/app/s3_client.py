"""S3/MinIO client factory for the storage worker.

Uses environment variables for configuration, falling back to local
development defaults (MinIO on localhost:9000).
"""

import os

import boto3


def get_s3_client():
    """Create and return a configured boto3 S3 client.

    Environment variables:
        S3_ENDPOINT: S3-compatible endpoint URL (default: http://localhost:9000)
        S3_ACCESS_KEY: AWS/MinIO access key (default: agentguard)
        S3_SECRET_KEY: AWS/MinIO secret key (default: agentguard_dev)
    """
    return boto3.client(
        "s3",
        endpoint_url=os.environ.get("S3_ENDPOINT", "http://localhost:9000"),
        aws_access_key_id=os.environ.get("S3_ACCESS_KEY", "agentguard"),
        aws_secret_access_key=os.environ.get("S3_SECRET_KEY", "agentguard_dev"),
    )
