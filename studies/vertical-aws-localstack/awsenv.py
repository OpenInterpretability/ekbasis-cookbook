"""Local-only AWS: every client is forced to LocalStack on 127.0.0.1:4566 with the dummy credentials "test"/"test".
Any request that tried to reach real AWS would go through a dead proxy (127.0.0.1:9) and fail loudly."""
import os

ENDPOINT = "http://127.0.0.1:4566"
REGION = "us-east-1"
SAFE_ENV = {
    "AWS_ACCESS_KEY_ID": "test", "AWS_SECRET_ACCESS_KEY": "test", "AWS_DEFAULT_REGION": REGION, "AWS_REGION": REGION,
    "AWS_CONFIG_FILE": "/dev/null", "AWS_SHARED_CREDENTIALS_FILE": "/dev/null", "AWS_EC2_METADATA_DISABLED": "true",
    "HTTPS_PROXY": "http://127.0.0.1:9", "HTTP_PROXY": "http://127.0.0.1:9",
    "https_proxy": "http://127.0.0.1:9", "http_proxy": "http://127.0.0.1:9",
    "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost",
}
for k in ("AWS_PROFILE", "AWS_SESSION_TOKEN", "AWS_ENDPOINT_URL"):
    os.environ.pop(k, None)
os.environ.update(SAFE_ENV)

import boto3  # noqa: E402
from botocore.config import Config  # noqa: E402
from botocore import UNSIGNED  # noqa: E402


def client(svc, unsigned=False, key="test", secret="test", token=None):
    cfg = Config(retries={"max_attempts": 1}, connect_timeout=2, read_timeout=60,
                 s3={"addressing_style": "path"}, **({"signature_version": UNSIGNED} if unsigned else {}))
    c = boto3.client(svc, endpoint_url=ENDPOINT, region_name=REGION, aws_access_key_id=key,
                     aws_secret_access_key=secret, aws_session_token=token, config=cfg)
    assert c.meta.endpoint_url.startswith("http://127.0.0.1:4566"), c.meta.endpoint_url
    return c
