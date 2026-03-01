import json


def load_from_secrets_manager(prefix):
    """Fetch all secrets under a Secrets Manager prefix.

    Secrets with JSON object values are expanded into multiple keys.
    Plain strings use the last path component as the key name.

    Returns {KEY: value} dict, or {} on any error.
    """
    if not prefix:
        return {}
    try:
        import boto3
        client = boto3.client("secretsmanager")
        secrets = {}
        paginator = client.get_paginator("list_secrets")
        for page in paginator.paginate(Filters=[{"Key": "name", "Values": [prefix]}]):
            for secret in page["SecretList"]:
                try:
                    val = client.get_secret_value(SecretId=secret["ARN"])["SecretString"]
                    try:
                        parsed = json.loads(val)
                        if isinstance(parsed, dict):
                            secrets.update({k: str(v) for k, v in parsed.items()})
                            continue
                    except (json.JSONDecodeError, TypeError):
                        pass
                    key = secret["Name"].rstrip("/").split("/")[-1].upper()
                    secrets[key] = val
                except Exception:
                    pass
        return secrets
    except Exception:
        return {}
