"""AWS plan guard (pilot, not shipped): state from FACTS (the plan JSON + live facts read before the apply), typed
questions to Ekbasis, verdict decided in code. The rule baseline is in rule.py.

    state = build_state(plan, facts)
    answers = client.ask(state, QUESTIONS)
    verdict = decide({k: a.p_yes for k, a in answers.items()})
"""
from __future__ import annotations

import hashlib
import json
import re

from ekbasis import prompts as P

import notes as N

RULES = ("An OpenTofu (Terraform) plan is about to be applied to an AWS account (one region). Running applications use "
         "these resources by name: they read and write objects, table items, queue messages, secrets and parameters, "
         "and invoke functions. Applying the plan carries out the resource changes below in dependency order. "
         "Replacing a resource destroys the old one and then creates the new one, unless the plan says the new one is "
         "created first (create_before_destroy). If a change fails, the apply stops there; the changes already made "
         "stay made.")

Q_LOST = P.yes_no(
    "Does applying this plan permanently lose stored data that exists before it: objects in an S3 bucket, items in a "
    "DynamoDB table, messages waiting in an SQS queue, or a secret or parameter value that an application wrote, so "
    "that afterwards it cannot be read or restored from anywhere? A noncurrent object version, a parameter's earlier "
    "value in its history, a secret's previous version, and a secret scheduled for deletion that can still be restored "
    "are not lost. Content that OpenTofu itself writes from the configuration does not count. If a change fails, only "
    "what was done before it counts.")
Q_DOWN = P.yes_no(
    "Does a resource that answers before the apply stop answering clients that use it by its current name, at some "
    "moment during the apply or right after it: the bucket, the table, the queue, the topic, the function, reading the "
    "secret's value or the parameter? A short gap while a resource is replaced counts, and so does a read that fails "
    "because the resource is gone, renamed or scheduled for deletion. A change that fails without touching the "
    "resource does not.")
Q_FAILS = P.yes_no("Does applying this plan fail (some change ends with an error)?")
QUESTIONS = {"lost": Q_LOST, "down": Q_DOWN, "fails": Q_FAILS}
THRESHOLD = 0.5


def fmt(v):
    if v is True or v is False:
        return "true" if v else "false"
    if v is None:
        return "null"
    if isinstance(v, list):
        return "[" + ", ".join(fmt(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{" + ", ".join(f"{k} = {fmt(x)}" for k, x in v.items() if x not in (None, "", [], {})) + "}"
    if isinstance(v, str):
        try:
            j = json.loads(v)
            if isinstance(j, (dict, list)):
                return json.dumps(j, separators=(",", ":"))
        except ValueError:
            pass
        return json.dumps(v)
    return str(v)


def plural(k, word):
    return f"{k:,} {word}{'' if k == 1 else 's'}"


# ---------------------------------------------------------------- current state

def describe(addr, typ, v, f, prior):
    f = f or {}
    if typ == "aws_s3_bucket":
        if not f.get("exists"):
            return f"{addr}: bucket {v.get('bucket')} (not found in the account)"
        bits = [f"{addr}: bucket {v.get('bucket')}", f"holds {plural(f['objects'], 'object')}"
                + (f" and {plural(f['noncurrent_versions'], 'noncurrent version')}" if f["noncurrent_versions"] else ""),
                f"versioning {f['versioning']}", f"force_destroy = {fmt(v.get('force_destroy'))} in the state"]
        return "; ".join(bits)
    if typ == "aws_s3_bucket_versioning":
        st = (v.get("versioning_configuration") or [{}])[0].get("status")
        return f"{addr}: versioning {st} on bucket {v.get('bucket')}"
    if typ == "aws_s3_object":
        line = f"{addr}: object {v.get('key')} in bucket {v.get('bucket')}, written by OpenTofu from the configuration"
        if not f.get("exists"):
            return line + "; the object is missing from the bucket"
        if f.get("etag") != hashlib.md5((v.get("content") or "").encode()).hexdigest():
            return line + "; the object in the bucket was overwritten after OpenTofu wrote it (its content differs)"
        return line + "; same content as OpenTofu wrote"
    if typ == "aws_s3_bucket_policy":
        return f"{addr}: bucket policy on {v.get('bucket')}: {fmt(v.get('policy'))}"
    if typ == "aws_s3_bucket_public_access_block":
        return (f"{addr}: public access block on {v.get('bucket')} (block_public_policy = "
                f"{fmt(v.get('block_public_policy'))}, restrict_public_buckets = {fmt(v.get('restrict_public_buckets'))})")
    if typ == "aws_dynamodb_table":
        if not f.get("exists"):
            return f"{addr}: table {v.get('name')} (not found in the account)"
        keys = f"hash key {v.get('hash_key')}" + (f", range key {v.get('range_key')}" if v.get("range_key") else "")
        return (f"{addr}: table {v.get('name')} ({keys}, billing {v.get('billing_mode')}); holds "
                f"{plural(f['items'], 'item')}; deletion protection {'on' if f['deletion_protection'] else 'off'}")
    if typ == "aws_sqs_queue":
        if not f.get("exists"):
            return f"{addr}: queue {v.get('name')} (not found in the account)"
        extra = f" and {f['in_flight']} in flight" if f.get("in_flight") else ""
        rd = ", sends failed messages to a dead-letter queue" if v.get("redrive_policy") else ""
        return f"{addr}: queue {v.get('name')}{rd}; {plural(f['messages'], 'message')} waiting{extra}"
    if typ == "aws_sns_topic":
        if not f.get("exists"):
            return f"{addr}: topic {v.get('name')} (not found in the account)"
        return f"{addr}: topic {v.get('name')}; {plural(f['subscriptions'], 'subscription')}"
    if typ == "aws_sns_topic_subscription":
        return f"{addr}: subscription of {v.get('endpoint')} ({v.get('protocol')}) to {v.get('topic_arn')}"
    if typ == "aws_secretsmanager_secret":
        if not f.get("exists"):
            return f"{addr}: secret {v.get('name')} (not found in the account)"
        w = v.get("recovery_window_in_days")
        bits = [f"{addr}: secret {v.get('name')}", f"recovery_window_in_days = {w if w is not None else 30} in the state"]
        vs = f.get("versions") or []
        tf_ids = {x.get("version_id") for x in prior.values() if x.get("secret_id") == v.get("arn")}
        cur = [x for x in vs if "AWSCURRENT" in x["stages"]]
        if cur:
            who = "OpenTofu" if cur[0]["id"] in tf_ids else "an application (not OpenTofu)"
            bits.append(f"has a current value, written by {who}; {plural(len(vs), 'version')} in all")
        else:
            bits.append("has no value")
        if f.get("scheduled_for_deletion"):
            bits.append("scheduled for deletion")
        return "; ".join(bits)
    if typ == "aws_secretsmanager_secret_version":
        cur = None
        for x in ((f.get("secret") or {}).get("versions") or []):
            if x["id"] == v.get("version_id"):
                cur = x["stages"]
        st = f"now labelled {', '.join(cur)}" if cur else "no longer labelled current"
        name = re.sub(r"-[A-Za-z0-9]{6}$", "", v.get("secret_id", "").rsplit(":", 1)[-1])
        return f"{addr}: the secret value OpenTofu wrote to {name} ({st})"
    if typ == "aws_ssm_parameter":
        if not f.get("exists"):
            return f"{addr}: parameter {v.get('name')} (not found in the account)"
        changed = f.get("value") != v.get("value")
        return (f"{addr}: parameter {v.get('name')}, type {v.get('type')}, tier {v.get('tier')}; at version "
                f"{f['version']} ({plural(f['version'], 'value')} in its history); its current value "
                + ("was written outside OpenTofu (it differs from the value in the state)" if changed
                   else "is the one in the state"))
    if typ == "aws_lambda_function":
        if not f.get("exists"):
            return f"{addr}: function {v.get('function_name')} (not found in the account)"
        return f"{addr}: function {v.get('function_name')}, runtime {v.get('runtime')}, {f.get('state', '').lower()}"
    if typ == "aws_iam_role":
        return f"{addr}: IAM role {v.get('name')}, trust policy {fmt(v.get('assume_role_policy'))}"
    if typ == "aws_iam_role_policy":
        return f"{addr}: inline policy {v.get('name')} on role {v.get('role')}: {fmt(v.get('policy'))}"
    if typ == "terraform_data":
        return f"{addr}: a revision marker (input {fmt(v.get('input'))})"
    return f"{addr}: {typ}"


def resources(plan):
    out = {}

    def walk(m):
        for r in m.get("resources") or []:
            if r.get("mode") == "managed":
                out[r["address"]] = (r["type"], r.get("values") or {})
        for c in m.get("child_modules") or []:
            walk(c)

    walk(((plan.get("prior_state") or {}).get("values") or {}).get("root_module") or {})
    return out


def current_state(plan, facts):
    res = resources(plan)
    if not res:
        return ["(nothing is managed yet)"]
    prior = {a: v for a, (t, v) in res.items() if t == "aws_secretsmanager_secret_version"}
    return [describe(a, t, v, facts["resources"].get(a), prior) for a, (t, v) in res.items()]


# ---------------------------------------------------------------- the changes

REASONS = {
    "replace_because_cannot_update": "a changed attribute cannot be updated in place",
    "replace_because_tainted": "it is tainted",
    "replace_by_request": "replacement was requested",
    "replace_by_triggers": "a replace_triggered_by reference changed",
    "delete_because_no_resource_config": "it was removed from the configuration",
    "delete_because_no_module": "its module was removed",
}
NOISE = {"id", "arn", "tags_all", "region", "version_id", "etag", "url", "invoke_arn", "qualified_arn",
         "qualified_invoke_arn", "last_modified", "source_code_size", "version", "stream_arn", "stream_label",
         "hosted_zone_id", "bucket_domain_name", "bucket_regional_domain_name", "website_domain", "website_endpoint",
         "unique_id", "create_date", "signing_job_arn", "signing_profile_version_arn", "has_value_wo",
         "secret_string_wo_version", "key_id", "insecure_value", "bucket_prefix", "name_prefix",
         "acceleration_status", "request_payer", "policy", "owner", "beginning_arn", "code_sha256",
         "image_uri", "response_streaming_invoke_arn", "source_code_hash"}
SHOW_COMPUTED = {"name", "bucket", "function_name", "force_destroy"}


def changed_attrs(rc):
    ch = rc["change"]
    before, after = ch.get("before") or {}, ch.get("after") or {}
    unknown = ch.get("after_unknown") or {}
    forced = {p[0] for p in ch.get("replace_paths") or [] if p}
    out = []
    for k in sorted(set(before) | set(after) | set(unknown)):
        if k in NOISE and k not in forced:
            continue
        b, a, u = before.get(k), after.get(k), unknown.get(k)
        if u is True or (u and a in (None, [], {})):
            if k in forced:
                out.append(f"{k}: {fmt(b)} -> (known after apply)")
            continue
        if b == a or (a in (None, [], {}, "") and b in (None, [], {}, "", 0, False)):
            continue
        if "delete" in ch["actions"] and "create" in ch["actions"] and a in (None, [], {}) and k not in forced:
            continue
        out.append(f"{k}: {fmt(b)} -> {fmt(a)}")
    return out, forced


CREATED = {"aws_s3_bucket": ("bucket", "force_destroy"), "aws_s3_bucket_versioning": ("bucket", "versioning_configuration"),
           "aws_s3_object": ("bucket", "key", "content"), "aws_s3_bucket_policy": ("bucket", "policy"),
           "aws_s3_bucket_public_access_block": ("bucket", "block_public_policy", "restrict_public_buckets"),
           "aws_dynamodb_table": ("name", "hash_key", "range_key", "deletion_protection_enabled"),
           "aws_sqs_queue": ("name", "fifo_queue", "redrive_policy"), "aws_sns_topic": ("name",),
           "aws_sns_topic_subscription": ("protocol",), "aws_secretsmanager_secret": ("name", "recovery_window_in_days"),
           "aws_secretsmanager_secret_version": ("secret_string",), "aws_ssm_parameter": ("name", "type", "tier"),
           "aws_lambda_function": ("function_name", "runtime"), "aws_iam_role": ("name", "assume_role_policy"),
           "aws_iam_role_policy": ("name", "policy"), "terraform_data": ("input",)}


def created_attrs(rc):
    a = rc["change"].get("after") or {}
    out = []
    for k in CREATED.get(rc["type"], ()):
        x = a.get(k)
        if x in (None, [], {}):
            continue
        if k == "secret_string":
            x = "(a value from the configuration)"
            out.append(f"{k} = {x}")
            continue
        out.append(f"{k} = {fmt(x)}")
    return out


def taken(rc, facts):
    t = (facts.get("name_taken") or {}).get(rc["address"])
    if not t or not t["exists"]:
        return ""
    s = " (scheduled for deletion)" if t.get("scheduled_for_deletion") else ""
    return f" [the name {t['name']} is already taken by an existing resource{s}]"


def action_line(rc, facts):
    ch = rc["change"]
    acts = ch["actions"]
    addr = rc["address"]
    why = REASONS.get(rc.get("action_reason") or "", "")
    if acts == ["create"]:
        attrs = created_attrs(rc)
        return f"Create {addr}" + (": " + "; ".join(attrs) if attrs else "") + taken(rc, facts)
    if acts == ["delete"]:
        return f"Destroy {addr}" + (f" ({why})" if why else "")
    if acts == ["forget"]:
        return f"Stop managing {addr}: it is removed from the OpenTofu state and left as it is (not destroyed)"
    attrs, forced = changed_attrs(rc)
    ch_text = "; ".join(attrs[:10]) if attrs else "no attribute shown"
    if acts == ["update"]:
        return f"Update {addr} in place: {ch_text}"
    if acts in (["delete", "create"], ["create", "delete"]):
        order = ("destroy the old one, then create the new one" if acts[0] == "delete"
                 else "create the new one first, then destroy the old one (create_before_destroy)")
        f = f", forced by the change to {', '.join(sorted(forced))}" if forced else (f", because {why}" if why else "")
        return f"Replace {addr} ({order}{f}): {ch_text}" + taken(rc, facts)
    return f"{'/'.join(acts)} {addr}: {ch_text}"


def changes(plan):
    return [rc for rc in plan.get("resource_changes") or [] if rc["mode"] == "managed"
            and rc["change"]["actions"] not in (["no-op"], ["read"])]


def build_state(plan, facts):
    rcs = changes(plan)
    acts = [action_line(rc, facts) for rc in rcs]
    moved = [f"{rc['previous_address']} is now {rc['address']} (moved; no change)"
             for rc in plan.get("resource_changes") or []
             if rc.get("previous_address") and rc["change"]["actions"] == ["no-op"]]
    if not acts:
        acts = ["Apply the plan: it changes no resource" + (" (" + "; ".join(moved) + ")" if moved else "")]
    elif moved:
        acts.append("Record the moves: " + "; ".join(moved))
    state = "\n".join(current_state(plan, facts))
    return P.world_state(RULES, state, acts, notes=N.notes_for(plan), notes_label="How these resources behave")


# ---------------------------------------------------------------- the verdict, in code

def decide(p: dict, threshold: float = THRESHOLD) -> dict:
    """p: {"lost", "down", "fails"} -> probabilities. Verdict and reason decided here, not by the model."""
    flags = [k for k in ("lost", "down") if p.get(k, 0) >= threshold]
    words = {"lost": "may permanently lose stored data", "down": "may interrupt a resource clients use by name"}
    if not flags:
        reason = f"no data loss or interruption foreseen (lose {p['lost']:.0%}, interrupt {p['down']:.0%})"
    else:
        reason = "; ".join(f"{words[k]} ({p[k]:.0%})" for k in flags)
    if p.get("fails", 0) >= threshold:
        reason += f"; the apply may fail part-way ({p['fails']:.0%})"
    return {"risky": bool(flags), "flags": flags, "reason": reason}
