"""Secrets Manager resolution helper for provider API keys."""

import os

import boto3


def resolve_secret(secret_name: str) -> str:
    """Resolve a secret string from AWS Secrets Manager by name or ARN."""
    region = os.environ.get("AWS_REGION", "us-east-1")
    client = boto3.client("secretsmanager", region_name=region)
    resp = client.get_secret_value(SecretId=secret_name)
    return resp["SecretString"]
