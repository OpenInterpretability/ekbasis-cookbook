"""Rule baseline for the AWS plan guard pilot. FROZEN in PREREG.md (sha256 there); never changed after."""
from __future__ import annotations

import json


def changes(plan):
    return [rc for rc in plan.get("resource_changes") or [] if rc["mode"] == "managed"
            and rc["change"]["actions"] not in (["no-op"], ["read"])]


DATA = {"aws_s3_bucket", "aws_s3_object", "aws_dynamodb_table", "aws_sqs_queue", "aws_secretsmanager_secret",
        "aws_secretsmanager_secret_version", "aws_ssm_parameter"}
SERVING = DATA | {"aws_sns_topic", "aws_lambda_function"}


def wide_principal(doc):
    try:
        d = json.loads(doc) if isinstance(doc, str) else doc
    except (TypeError, ValueError):
        return False
    for st in (d or {}).get("Statement") or []:
        pr = st.get("Principal")
        if st.get("Effect") == "Allow" and (pr == "*" or (isinstance(pr, dict) and "*" in (
                pr.get("AWS") if isinstance(pr.get("AWS"), list) else [pr.get("AWS")]))):
            return True
    return False


def rule(plan) -> dict:
    """R_lost: any delete (or replace) of a resource that holds data: aws_s3_bucket, aws_s3_object, aws_dynamodb_table,
    aws_sqs_queue, aws_secretsmanager_secret(_version), aws_ssm_parameter.
    R_down: any delete or destroy-before-create replace of a resource clients use by name: the same types plus
    aws_sns_topic and aws_lambda_function.
    R_exposed (reported, not evaluated: exposure is not labelled): a created/updated policy with an Allow for
    Principal "*", or a removed public access block."""
    out = {"lost": False, "down": False, "exposed": False}
    for rc in changes(plan):
        ch, typ = rc["change"], rc["type"]
        acts = ch["actions"]
        a = ch.get("after") or {}
        if "delete" in acts:
            if typ in DATA:
                out["lost"] = True
            if typ in SERVING and acts[0] == "delete":
                out["down"] = True
            if typ == "aws_s3_bucket_public_access_block":
                out["exposed"] = True
        if "create" in acts or "update" in acts:
            for k in ("policy", "assume_role_policy"):
                if a.get(k) and wide_principal(a[k]):
                    out["exposed"] = True
    out["risky"] = out["lost"] or out["down"]
    return out
