"""Executes each scenario against LocalStack and labels it from what actually happened (no model involved):
apply v1 -> seed data -> plan v2 (saved: plan.json + live facts) -> apply the saved plan while probing by name
-> search for the seeded data -> clean up.

Labels (down also counts a replace gap: see replace_gaps): lost (some seeded datum can no longer be read or restored from anywhere in the scenario: any bucket and any
object version, any table, any queue, any secret including AWSPREVIOUS and secrets scheduled for deletion (restorable),
any parameter including its history), down (a probe that succeeded 3/3 before fails at some moment during the apply or
in the 3 s after), failed (tofu apply exits non-zero). Exposure is NOT labelled: LocalStack Community does not enforce
IAM, bucket policies or function URL auth (fidelity/README.md).

usage: runner.py [ids...]   (results in runs/s<id>/result.json)
"""
from __future__ import annotations

import json
import os
import secrets
import shutil
import subprocess
import sys
import threading
import time

import awsenv as A
import facts as F
import scenarios as SC

ROOT = os.path.dirname(os.path.abspath(__file__))
RUNS = os.path.join(ROOT, "runs")
ASSETS = os.path.join(ROOT, "assets")
BASE_ENV = dict(os.environ, TF_PLUGIN_CACHE_DIR=os.path.join(ROOT, "plugin-cache"), TF_IN_AUTOMATION="1",
                TF_INPUT="0", CHECKPOINT_DISABLE="1")
for k in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy"):
    BASE_ENV.pop(k, None)
INIT_ENV = dict(BASE_ENV, AWS_CONFIG_FILE="/dev/null", AWS_SHARED_CREDENTIALS_FILE="/dev/null")   # registry only
RUN_ENV = dict(BASE_ENV, **A.SAFE_ENV)    # plan/apply: dead proxy for anything that is not 127.0.0.1
for k in ("AWS_PROFILE", "AWS_SESSION_TOKEN", "AWS_ENDPOINT_URL"):
    RUN_ENV.pop(k, None)


def sh(args, cwd=None, timeout=600, env=None):
    r = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)
    return r.returncode, r.stdout + r.stderr


def tofu(d, *args, timeout=900, env=RUN_ENV):
    return sh(["tofu", *args, "-no-color"], cwd=d, timeout=timeout, env=env)


def subst(text):
    return text.replace("@ASSETS@", ASSETS)


# ---------------------------------------------------------------- clients

s3, ddb, sqs, sns, sm, ssm, lam = (A.client(x) for x in ("s3", "dynamodb", "sqs", "sns", "secretsmanager", "ssm",
                                                        "lambda"))


def qurl(name):
    return sqs.get_queue_url(QueueName=name)["QueueUrl"]


# ---------------------------------------------------------------- seeding (what an application writes)

def seed(op, tok):
    k = op["op"]
    if k == "s3_objects":
        for j in range(op["n"]):
            s3.put_object(Bucket=op["bucket"], Key=f"data/obj{j:03d}.json", Body=f'{{"v": "{tok}", "j": {j}}}'.encode())
    elif k == "s3_put":
        s3.put_object(Bucket=op["bucket"], Key=op["key"], Body=f'{{"written_by": "app", "v": "{tok}"}}'.encode())
    elif k == "ddb_items":
        for j in range(op["n"]):
            key = {"S": f"k{j:04d}"} if op["type"] == "S" else {"N": str(j)}
            ddb.put_item(TableName=op["table"], Item={op["key"]: key, "v": {"S": f"{tok}:{op['table']}"},
                                                     "email": {"S": f"u{j}@x.io"}})
    elif k == "sqs_msgs":
        u = qurl(op["queue"])
        for j in range(op["n"]):
            sqs.send_message(QueueUrl=u, MessageBody=f"{tok} job {j}")
    elif k == "secret_value":
        sm.put_secret_value(SecretId=op["name"], SecretString=tok)
    elif k == "ssm_value":
        ssm.put_parameter(Name=op["name"], Value=tok, Type="String", Overwrite=True)
    else:
        raise ValueError(op)


# ---------------------------------------------------------------- probes (a client reading by name)

def probe_once(p):
    try:
        k, name = p["kind"], p["name"]
        if k == "s3":
            s3.head_bucket(Bucket=name)
        elif k == "ddb":
            ddb.describe_table(TableName=name)
        elif k == "sqs":
            sqs.get_queue_attributes(QueueUrl=qurl(name), AttributeNames=["QueueArn"])
        elif k == "sns":
            sns.get_topic_attributes(TopicArn=f"arn:aws:sns:us-east-1:{SC.ACCOUNT}:{name}")
        elif k == "secret":
            sm.get_secret_value(SecretId=name)
        elif k == "ssm":
            ssm.get_parameter(Name=name)
        elif k == "lambda":
            r = lam.invoke(FunctionName=name)
            if r.get("FunctionError"):
                return False
        else:
            raise ValueError(p)
        return True
    except ValueError:
        raise
    except Exception:
        return False


class Prober(threading.Thread):
    """One thread per probe, so a slow probe (a Lambda cold start) does not hide the others."""

    def __init__(self, p):
        super().__init__(daemon=True)
        self.p, self.stop, self.fail, self.n = p, threading.Event(), 0, 0

    def run(self):
        while not self.stop.is_set():
            if not probe_once(self.p):
                self.fail += 1
            self.n += 1
            time.sleep(0.2)


# ---------------------------------------------------------------- data search

def scen_buckets(i):
    return [b["Name"] for b in s3.list_buckets().get("Buckets", []) if b["Name"].startswith(f"vaws-s{i}-")]


def all_versions(b):
    out = []
    for page in s3.get_paginator("list_object_versions").paginate(Bucket=b):
        for v in page.get("Versions", []):
            out.append((v["Key"], v["VersionId"]))
    return out


def body(b, key, vid=None):
    kw = {"VersionId": vid} if vid and vid != "null" else {}
    return s3.get_object(Bucket=b, Key=key, **kw)["Body"].read().decode()


def find_store(i, op, tok):
    """(found, total, where): how many of the seeded data are still readable or restorable."""
    k = op["op"]
    if k in ("s3_objects", "s3_put"):
        want = {f"data/obj{j:03d}.json" for j in range(op["n"])} if k == "s3_objects" else {op["key"]}
        seen, where = set(), []
        for b in scen_buckets(i):
            for key, vid in all_versions(b):
                if key in want and key not in seen and tok in body(b, key, vid):
                    seen.add(key)
                    where.append(b)
        return len(seen), len(want), sorted(set(where))
    if k == "ddb_items":
        found, where = 0, []
        for t in ddb.list_tables()["TableNames"]:
            if t.startswith(f"vaws-s{i}-"):
                c = 0
                for page in ddb.get_paginator("scan").paginate(TableName=t):
                    # the value names the table it was seeded into: two seeded tables are two separate stores
                    c += sum(1 for it in page["Items"] if it.get("v", {}).get("S") == f"{tok}:{op['table']}")
                if c:
                    where.append(f"{t} ({c})")
                found = max(found, c)
        return found, op["n"], where
    if k == "sqs_msgs":
        found, where = 0, []
        for u in sqs.list_queues(QueueNamePrefix=f"vaws-s{i}-").get("QueueUrls", []):
            at = sqs.get_queue_attributes(QueueUrl=u, AttributeNames=["All"])["Attributes"]
            c = sum(int(at.get(x, 0)) for x in ("ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible",
                                                "ApproximateNumberOfMessagesDelayed"))
            if c:
                where.append(f"{u.rsplit('/', 1)[1]} ({c})")
            found += c
        return min(found, op["n"]), op["n"], where
    if k == "secret_value":
        where = []
        for sct in sm.list_secrets(IncludePlannedDeletion=True)["SecretList"]:
            if not sct["Name"].startswith(f"vaws-s{i}-"):
                continue
            restorable = "DeletedDate" in sct
            if restorable:
                sm.restore_secret(SecretId=sct["ARN"])    # only after labelling: proves it can be restored
            for stage in ("AWSCURRENT", "AWSPREVIOUS"):
                try:
                    if sm.get_secret_value(SecretId=sct["ARN"], VersionStage=stage).get("SecretString") == tok:
                        where.append(f"{sct['Name']} {stage}" + (" (restored from scheduled deletion)" if restorable else ""))
                except Exception:
                    pass
        return int(bool(where)), 1, where
    if k == "ssm_value":
        where = []
        for page in ssm.get_paginator("describe_parameters").paginate(
                ParameterFilters=[{"Key": "Name", "Option": "BeginsWith", "Values": [f"/vaws/s{i}/"]}]):
            for prm in page["Parameters"]:
                hist = ssm.get_parameter_history(Name=prm["Name"], WithDecryption=True)["Parameters"]
                if any(h.get("Value") == tok for h in hist):
                    where.append(prm["Name"])
        return int(bool(where)), 1, where
    raise ValueError(op)


# ---------------------------------------------------------------- replace gap

NAME_ATTR = {"aws_s3_bucket": "bucket", "aws_dynamodb_table": "name", "aws_sqs_queue": "name", "aws_sns_topic": "name",
             "aws_secretsmanager_secret": "name", "aws_ssm_parameter": "name", "aws_lambda_function": "function_name"}


def replace_gaps(plan, apply_out, probes):
    """Names that clients probe and that did not exist for an interval during the apply: a destroy-then-create replace
    that keeps the name, whose destruction completed (the provider waits for the deletion before it creates the new
    one). LocalStack deletes and creates some resources at once, so a 0.2 s probe can miss this gap; AWS cannot."""
    names = {p["name"] for p in probes}
    out = []
    for rc in plan.get("resource_changes") or []:
        if rc["change"]["actions"] != ["delete", "create"] or rc["type"] not in NAME_ATTR:
            continue
        k = NAME_ATTR[rc["type"]]
        b, a = (rc["change"].get("before") or {}).get(k), (rc["change"].get("after") or {}).get(k)
        if b == a and b in names and f"{rc['address']}: Destruction complete" in apply_out:
            out.append(b)
    return out


# ---------------------------------------------------------------- cleanup (everything named for the scenario)

def sweep(i):
    pre = f"vaws-s{i}-"
    for b in scen_buckets(i):
        try:
            vs = s3.list_object_versions(Bucket=b)
            objs = [{"Key": v["Key"], "VersionId": v["VersionId"]} for v in vs.get("Versions", []) + vs.get("DeleteMarkers", [])]
            for j in range(0, len(objs), 500):
                s3.delete_objects(Bucket=b, Delete={"Objects": objs[j:j + 500]})
            s3.delete_bucket(Bucket=b)
        except Exception as e:
            print("sweep bucket", b, e)
    for t in ddb.list_tables()["TableNames"]:
        if t.startswith(pre):
            try:
                ddb.update_table(TableName=t, DeletionProtectionEnabled=False)
            except Exception:
                pass
            ddb.delete_table(TableName=t)
    for u in sqs.list_queues(QueueNamePrefix=pre).get("QueueUrls", []):
        sqs.delete_queue(QueueUrl=u)
    for t in sns.list_topics()["Topics"]:
        if t["TopicArn"].rsplit(":", 1)[1].startswith(pre):
            sns.delete_topic(TopicArn=t["TopicArn"])
    for sct in sm.list_secrets(IncludePlannedDeletion=True)["SecretList"]:
        if sct["Name"].startswith(pre):
            if "DeletedDate" in sct:
                sm.restore_secret(SecretId=sct["ARN"])
            sm.delete_secret(SecretId=sct["ARN"], ForceDeleteWithoutRecovery=True)
    for page in ssm.get_paginator("describe_parameters").paginate(
            ParameterFilters=[{"Key": "Name", "Option": "BeginsWith", "Values": [f"/vaws/s{i}/"]}]):
        for prm in page["Parameters"]:
            ssm.delete_parameter(Name=prm["Name"])
    for f in lam.list_functions()["Functions"]:
        if f["FunctionName"].startswith(pre):
            lam.delete_function(FunctionName=f["FunctionName"])
    iam = A.client("iam")
    for r in iam.list_roles()["Roles"]:
        if r["RoleName"].startswith(pre):
            for pn in iam.list_role_policies(RoleName=r["RoleName"])["PolicyNames"]:
                iam.delete_role_policy(RoleName=r["RoleName"], PolicyName=pn)
            iam.delete_role(RoleName=r["RoleName"])


def run(s):
    i = s["id"]
    d = os.path.join(RUNS, f"s{i}")
    if os.path.isdir(d):
        shutil.rmtree(d)
    os.makedirs(d)
    sweep(i)
    tok = f"tok{i}x{secrets.token_hex(4)}"
    res = {"id": i, "title": s["title"], "family": s["family"], "split": s["split"], "token": tok}
    try:
        open(os.path.join(d, "main.tf"), "w").write(SC.HEADER + subst(s["v1"]))
        rc, out = tofu(d, "init", "-input=false", env=INIT_ENV)
        if rc:
            raise RuntimeError("init: " + out[-1500:])
        rc, out = tofu(d, "apply", "-auto-approve", "-input=false")
        if rc:
            raise RuntimeError("apply v1: " + out[-1500:])
        for op in s["seed"]:
            seed(op, tok)
        time.sleep(1)
        res["data_before"] = [find_store(i, op, tok) for op in s["seed"]]
        if any(f < t for f, t, _ in res["data_before"]):
            raise RuntimeError(f"seeded data not all found before the change: {res['data_before']}")
        open(os.path.join(d, "main.tf"), "w").write(SC.HEADER + subst(s["v2"]))
        rc, out = tofu(d, "plan", "-out=plan.bin", "-input=false")
        res["plan_text"] = out[-6000:]
        if rc:
            res["plan_error"] = out[-2000:]
            return res
        rc, pj = sh(["tofu", "show", "-json", "plan.bin"], cwd=d, env=RUN_ENV)
        open(os.path.join(d, "plan.json"), "w").write(pj)
        plan = json.loads(pj)
        fx = F.collect(plan)
        json.dump(fx, open(os.path.join(d, "facts.json"), "w"), indent=1, default=str)
        base = [all(probe_once(p) for _ in range(3)) for p in s["probes"]]
        res["probe_baseline_ok"] = base
        probers = [Prober(p) for p, ok in zip(s["probes"], base) if ok]
        for p in probers:
            p.start()
        t0 = time.time()
        rc, out = tofu(d, "apply", "-input=false", "plan.bin")
        res["apply_s"] = round(time.time() - t0, 1)
        time.sleep(3)
        for p in probers:
            p.stop.set()
        for p in probers:
            p.join()
        res["apply_rc"], res["apply_out"] = rc, out[-4000:]
        res["probe_fail"], res["probe_rounds"] = [p.fail for p in probers], [p.n for p in probers]
        time.sleep(1)
        res["data_after"] = [find_store(i, op, tok) for op in s["seed"]]
        res["replace_gaps"] = replace_gaps(plan, out, s["probes"])
        res["labels"] = {
            "lost": any(f < t for f, t, _ in res["data_after"]),
            "down": any(p.fail > 0 for p in probers) or bool(res["replace_gaps"]),
            "failed": rc != 0,
        }
    except Exception as e:
        res["error"] = f"{type(e).__name__}: {e}"[:3000]
    finally:
        json.dump(res, open(os.path.join(d, "result.json"), "w"), indent=1, default=str)
        try:
            tofu(d, "destroy", "-auto-approve", "-input=false", "-lock=false")
            sweep(i)
        except Exception as e:
            res["cleanup_error"] = str(e)
            json.dump(res, open(os.path.join(d, "result.json"), "w"), indent=1, default=str)
        shutil.rmtree(os.path.join(d, ".terraform"), ignore_errors=True)
    return res


if __name__ == "__main__":
    ids = [int(x) for x in sys.argv[1:]] or [s["id"] for s in SC.S]
    for i in ids:
        t = time.time()
        r = run(SC.BY_ID[i])
        print(f"s{i:<3} {time.time() - t:5.0f}s {r.get('labels') or r.get('error') or r.get('plan_error', '')[:300]}  "
              f"| {r['title']}", flush=True)
