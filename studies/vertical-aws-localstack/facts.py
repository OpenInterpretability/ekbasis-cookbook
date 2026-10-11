"""Live facts read (read-only) from the account before the apply, keyed by resource address. Only what a guard could
read with read-only credentials: object and version counts, versioning, item counts, deletion protection, messages
waiting, secret status and versions, parameter versions, and whether a name the plan creates is already taken."""
from __future__ import annotations

import awsenv as A

s3, ddb, sqs, sns, sm, ssm, lam = (A.client(x) for x in ("s3", "dynamodb", "sqs", "sns", "secretsmanager", "ssm",
                                                        "lambda"))


def safe(f):
    try:
        return f()
    except Exception as e:
        return {"error": type(e).__name__}


def bucket(name):
    try:
        s3.head_bucket(Bucket=name)
    except Exception:
        return {"exists": False}
    cur = noncur = markers = 0
    for page in s3.get_paginator("list_object_versions").paginate(Bucket=name):
        for v in page.get("Versions", []):
            if v["IsLatest"]:
                cur += 1
            else:
                noncur += 1
        markers += len(page.get("DeleteMarkers", []))
    ver = s3.get_bucket_versioning(Bucket=name).get("Status") or "never enabled"
    return {"exists": True, "objects": cur, "noncurrent_versions": noncur, "delete_markers": markers, "versioning": ver}


def table(name):
    try:
        t = ddb.describe_table(TableName=name)["Table"]
    except Exception:
        return {"exists": False}
    c = 0
    for page in ddb.get_paginator("scan").paginate(TableName=name, Select="COUNT"):
        c += page["Count"]
    return {"exists": True, "items": c, "deletion_protection": bool(t.get("DeletionProtectionEnabled")),
            "status": t.get("TableStatus")}


def queue(name):
    try:
        u = sqs.get_queue_url(QueueName=name)["QueueUrl"]
    except Exception:
        return {"exists": False}
    at = sqs.get_queue_attributes(QueueUrl=u, AttributeNames=["All"])["Attributes"]
    return {"exists": True, "messages": int(at.get("ApproximateNumberOfMessages", 0)),
            "in_flight": int(at.get("ApproximateNumberOfMessagesNotVisible", 0)),
            "redrive_source": "RedrivePolicy" in at}


def topic(name):
    arn = f"arn:aws:sns:us-east-1:000000000000:{name}"
    try:
        sns.get_topic_attributes(TopicArn=arn)
    except Exception:
        return {"exists": False}
    subs = sns.list_subscriptions_by_topic(TopicArn=arn)["Subscriptions"]
    return {"exists": True, "subscriptions": len(subs)}


def secret(name):
    for s in sm.list_secrets(IncludePlannedDeletion=True)["SecretList"]:
        if s["Name"] == name:
            out = {"exists": True, "scheduled_for_deletion": "DeletedDate" in s}
            vs = safe(lambda: sm.list_secret_version_ids(SecretId=s["ARN"])["Versions"])
            if isinstance(vs, list):
                out["versions"] = [{"id": v["VersionId"], "stages": v.get("VersionStages", [])} for v in vs]
            return out
    return {"exists": False}


def parameter(name):
    try:
        p = ssm.get_parameter(Name=name, WithDecryption=True)["Parameter"]
    except Exception:
        return {"exists": False}
    return {"exists": True, "version": p["Version"], "type": p["Type"], "value": p["Value"]}


def s3_object(bucket_name, key):
    try:
        h = s3.head_object(Bucket=bucket_name, Key=key)
        return {"exists": True, "etag": h["ETag"].strip('"')}
    except Exception:
        return {"exists": False}


def function(name):
    try:
        f = lam.get_function(FunctionName=name)["Configuration"]
        return {"exists": True, "state": f.get("State")}
    except Exception:
        return {"exists": False}


def name_of(typ, v):
    return {"aws_s3_bucket": v.get("bucket"), "aws_dynamodb_table": v.get("name"), "aws_sqs_queue": v.get("name"),
            "aws_sns_topic": v.get("name"), "aws_secretsmanager_secret": v.get("name"),
            "aws_ssm_parameter": v.get("name"), "aws_lambda_function": v.get("function_name")}.get(typ)


def live(typ, v):
    name = name_of(typ, v)
    if typ == "aws_s3_object":
        return s3_object(v.get("bucket"), v.get("key"))
    if not name:
        return None
    return {"aws_s3_bucket": bucket, "aws_dynamodb_table": table, "aws_sqs_queue": queue, "aws_sns_topic": topic,
            "aws_secretsmanager_secret": secret, "aws_ssm_parameter": parameter,
            "aws_lambda_function": function}[typ](name)


def walk(module):
    for r in module.get("resources") or []:
        if r.get("mode") == "managed":
            yield r
    for c in module.get("child_modules") or []:
        yield from walk(c)


def collect(plan):
    out = {"resources": {}, "name_taken": {}}
    prior = ((plan.get("prior_state") or {}).get("values") or {}).get("root_module") or {}
    for r in walk(prior):
        out["resources"][r["address"]] = safe(lambda: live(r["type"], r.get("values") or {}))
        if r["type"] == "aws_secretsmanager_secret_version":
            v = r.get("values") or {}
            out["resources"][r["address"]] = {"state_version_id": v.get("version_id"),
                                              "secret": safe(lambda: secret_by_arn(v.get("secret_id")))}
    for rc in plan.get("resource_changes") or []:
        if "create" in rc["change"]["actions"]:
            a = rc["change"].get("after") or {}
            name = name_of(rc["type"], a)
            if name:
                f = safe(lambda: live(rc["type"], a))
                out["name_taken"][rc["address"]] = {"name": name, "exists": bool(f and f.get("exists")),
                                                    "scheduled_for_deletion": bool(f and f.get("scheduled_for_deletion"))}
    return out


def secret_by_arn(arn):
    for s in sm.list_secrets(IncludePlannedDeletion=True)["SecretList"]:
        if s["ARN"] == arn:
            return secret(s["Name"])
    return {"exists": False}
