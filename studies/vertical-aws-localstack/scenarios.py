"""AWS plan guard pilot (LocalStack): change scenarios. ALL WRITTEN BY US (Claude, 2026-10-11), not collected from real
repos. Executed only against LocalStack Community 4.14.0 on 127.0.0.1:4566 with the dummy credentials "test"/"test".

Each scenario: v1 (applied first), seed (data an application writes after v1, before the plan), v2 (the change whose
plan is judged), probes (reads a client makes by name: measured during the apply). Every seed op is also a store: the
seeded data is searched for after the apply. Labels come only from executing the plan (runner.py).

split: "dev" (id % 3 == 0) may be used to develop the state builder; "test" is frozen by hash before any model call;
"fid" are provider-behaviour tests that prove the notes (never asked to the model).
"""
from __future__ import annotations

E = "http://127.0.0.1:4566"
SERVICES = ("s3", "dynamodb", "sqs", "sns", "iam", "lambda", "secretsmanager", "ssm", "sts")
HEADER = '''terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 6.0" }
  }
}
provider "aws" {
  region                      = "us-east-1"
  access_key                  = "test"
  secret_key                  = "test"
  skip_credentials_validation = true
  skip_metadata_api_check     = true
  skip_requesting_account_id  = true
  s3_use_path_style           = true
  endpoints {
''' + "".join(f'    {s} = "{E}"\n' for s in SERVICES) + '''  }
}
'''
ACCOUNT = "000000000000"


def n(i, x):
    return f"vaws-s{i}-{x}"


# ---------------------------------------------------------------- HCL helpers

def lc(*items):
    return "  lifecycle {\n" + "".join(f"    {x}\n" for x in items) + "  }\n" if items else ""


def bucket(i, addr="b", name="data", force=None, extra="", life=()):
    f = f"  force_destroy = {str(force).lower()}\n" if force is not None else ""
    return f'resource "aws_s3_bucket" "{addr}" {{\n  bucket = "{n(i, name)}"\n{f}{extra}{lc(*life)}}}\n'


def versioning(addr="b", status="Enabled"):
    return (f'resource "aws_s3_bucket_versioning" "{addr}" {{\n  bucket = aws_s3_bucket.{addr}.id\n'
            f'  versioning_configuration {{\n    status = "{status}"\n  }}\n}}\n')


def s3_object(addr="o", bucket_addr="b", key="config/app.json", content='{"mode": "a"}'):
    return (f'resource "aws_s3_object" "{addr}" {{\n  bucket  = aws_s3_bucket.{bucket_addr}.id\n  key     = "{key}"\n'
            f'  content = jsonencode({content})\n}}\n')


def public_policy(addr="b"):
    return (f'resource "aws_s3_bucket_policy" "{addr}" {{\n  bucket = aws_s3_bucket.{addr}.id\n'
            f'  policy = jsonencode({{ Version = "2012-10-17", Statement = [{{ Effect = "Allow", Principal = "*", '
            f'Action = "s3:GetObject", Resource = "${{aws_s3_bucket.{addr}.arn}}/*" }}] }})\n}}\n')


def pab(addr="b", on=True):
    v = str(on).lower()
    return (f'resource "aws_s3_bucket_public_access_block" "{addr}" {{\n  bucket = aws_s3_bucket.{addr}.id\n'
            f'  block_public_acls = {v}\n  block_public_policy = {v}\n  ignore_public_acls = {v}\n'
            f'  restrict_public_buckets = {v}\n}}\n')


def table(i, addr="t", name="items", hash_="pk", htype="S", range_=None, protect=None, extra="", life=(),
          billing="PAY_PER_REQUEST", attrs=()):
    a = [(hash_, htype)] + ([range_] if range_ else []) + list(attrs)
    attr = "".join(f'  attribute {{\n    name = "{k}"\n    type = "{t}"\n  }}\n' for k, t in a)
    rk = f'  range_key = "{range_[0]}"\n' if range_ else ""
    pr = f"  deletion_protection_enabled = {str(protect).lower()}\n" if protect is not None else ""
    cap = "  read_capacity = 5\n  write_capacity = 5\n" if billing == "PROVISIONED" else ""
    return (f'resource "aws_dynamodb_table" "{addr}" {{\n  name = "{n(i, name)}"\n  billing_mode = "{billing}"\n{cap}'
            f'  hash_key = "{hash_}"\n{rk}{attr}{pr}{extra}{lc(*life)}}}\n')


def queue(i, addr="q", name="jobs", extra="", life=()):
    return f'resource "aws_sqs_queue" "{addr}" {{\n  name = "{n(i, name)}"\n{extra}{lc(*life)}}}\n'


def topic(i, addr="tp", name="events", extra="", life=()):
    return f'resource "aws_sns_topic" "{addr}" {{\n  name = "{n(i, name)}"\n{extra}{lc(*life)}}}\n'


def secret(i, addr="s", name="db-password", window=None, extra="", life=()):
    w = f"  recovery_window_in_days = {window}\n" if window is not None else ""
    return f'resource "aws_secretsmanager_secret" "{addr}" {{\n  name = "{n(i, name)}"\n{w}{extra}{lc(*life)}}}\n'


def param(i, addr="p", name="app/endpoint", typ="String", value="https://api.internal/v1", ignore=True, extra="",
          life=()):
    life = (("ignore_changes = [value]",) if ignore else ()) + tuple(life)
    return (f'resource "aws_ssm_parameter" "{addr}" {{\n  name  = "/vaws/s{i}/{name}"\n  type  = "{typ}"\n'
            f'  value = "{value}"\n{extra}{lc(*life)}}}\n')


def role(i, addr="r", name="fn-role"):
    return (f'resource "aws_iam_role" "{addr}" {{\n  name = "{n(i, name)}"\n  assume_role_policy = jsonencode({{ '
            f'Version = "2012-10-17", Statement = [{{ Effect = "Allow", Principal = {{ Service = '
            f'"lambda.amazonaws.com" }}, Action = "sts:AssumeRole" }}] }})\n}}\n')


def fn(i, addr="f", name="worker", zip_="fn1", extra="", life=(), role_addr="r"):
    return (f'resource "aws_lambda_function" "{addr}" {{\n  function_name = "{n(i, name)}"\n'
            f'  role = aws_iam_role.{role_addr}.arn\n  handler = "index.handler"\n  runtime = "python3.12"\n'
            f'  filename = "@ASSETS@/{zip_}.zip"\n  source_code_hash = filebase64sha256("@ASSETS@/{zip_}.zip")\n'
            f'{extra}{lc(*life)}}}\n')


def trigger(v="1"):
    return f'resource "terraform_data" "rev" {{\n  input = "{v}"\n}}\n'


def removed(addr):
    return f"removed {{\n  from = {addr}\n  lifecycle {{\n    destroy = false\n  }}\n}}\n"


def moved(a, b):
    return f"moved {{\n  from = {a}\n  to   = {b}\n}}\n"


# ---------------------------------------------------------------- seeds and probes

def objs(i, name="data", k=20):
    return {"op": "s3_objects", "bucket": n(i, name), "n": k}


def items(i, name="items", key="pk", typ="S", k=200, range_=None):
    return {"op": "ddb_items", "table": n(i, name), "key": key, "type": typ, "n": k, "range": range_}


def msgs(i, name="jobs", k=30, fifo=False):
    return {"op": "sqs_msgs", "queue": n(i, name), "n": k, "fifo": fifo}


def secret_value(i, name="db-password"):
    return {"op": "secret_value", "name": n(i, name)}


def ssm_value(i, name="app/endpoint"):
    return {"op": "ssm_value", "name": f"/vaws/s{i}/{name}"}


def P(kind, name, **kw):
    return dict(kind=kind, name=name, **kw)


S = []


def add(i, title, family, v1, v2, seed=(), probes=(), split=None):
    S.append(dict(id=i, title=title, family=family, v1=v1, v2=v2, seed=list(seed), probes=list(probes),
                  split=split or ("dev" if i % 3 == 0 else "test")))


# ================================================================ S3 buckets (app objects under data/)
i = 1
add(i, "remove a bucket holding objects, force_destroy unset", "s3",
    bucket(i), "", [objs(i)], [P("s3", n(i, "data"))])
i = 2
add(i, "remove a bucket holding objects, force_destroy = true", "s3",
    bucket(i, force=True), "", [objs(i)], [P("s3", n(i, "data"))])
i = 3
add(i, "remove an empty bucket with force_destroy = true", "s3",
    bucket(i, force=True), "", [], [P("s3", n(i, "data"))])
i = 4
add(i, "rename a bucket holding objects, force_destroy unset", "s3",
    bucket(i), bucket(i, name="data2"), [objs(i)], [P("s3", n(i, "data"))])
i = 5
add(i, "rename a bucket holding objects, force_destroy = true", "s3",
    bucket(i, force=True), bucket(i, name="data2", force=True), [objs(i)], [P("s3", n(i, "data"))])
i = 6
add(i, "rename a bucket holding objects with create_before_destroy, force_destroy unset", "s3",
    bucket(i, life=("create_before_destroy = true",)),
    bucket(i, name="data2", life=("create_before_destroy = true",)), [objs(i)], [P("s3", n(i, "data"))])
i = 7
add(i, "rename a bucket and set force_destroy = true in the same change", "s3",
    bucket(i), bucket(i, name="data2", force=True), [objs(i)], [P("s3", n(i, "data"))])
i = 8
add(i, "set force_destroy = true on a bucket holding objects (nothing else)", "s3",
    bucket(i), bucket(i, force=True), [objs(i)], [P("s3", n(i, "data"))])
i = 9
add(i, "remove a versioned bucket holding objects, force_destroy = true", "s3",
    bucket(i, force=True) + versioning(), "", [objs(i)], [P("s3", n(i, "data"))])
i = 10
add(i, "enable versioning on a bucket holding objects", "s3",
    bucket(i), bucket(i) + versioning(), [objs(i)], [P("s3", n(i, "data"))])
i = 11
add(i, "suspend versioning on a versioned bucket holding objects", "s3",
    bucket(i) + versioning(), bucket(i) + versioning(status="Suspended"), [objs(i)], [P("s3", n(i, "data"))])
i = 12
add(i, "managed config object that the application overwrote, unversioned bucket, content changed", "s3",
    bucket(i) + s3_object(), bucket(i) + s3_object(content='{"mode": "b"}'),
    [{"op": "s3_put", "bucket": n(i, "data"), "key": "config/app.json"}], [P("s3", n(i, "data"))])
i = 13
add(i, "managed config object that the application overwrote, versioned bucket, content changed", "s3",
    bucket(i) + versioning() + s3_object(), bucket(i) + versioning() + s3_object(content='{"mode": "b"}'),
    [{"op": "s3_put", "bucket": n(i, "data"), "key": "config/app.json"}], [P("s3", n(i, "data"))])
i = 14
add(i, "move a managed config object to a new key, app objects elsewhere in the bucket", "s3",
    bucket(i) + s3_object(), bucket(i) + s3_object(key="config/app-v2.json"), [objs(i)], [P("s3", n(i, "data"))])
i = 15
add(i, "add a public-read bucket policy to a bucket holding objects", "s3",
    bucket(i), bucket(i) + public_policy(), [objs(i)], [P("s3", n(i, "data"))])
i = 16
add(i, "remove the public access block of a bucket holding objects", "s3",
    bucket(i) + pab(), bucket(i), [objs(i)], [P("s3", n(i, "data"))])
i = 17
add(i, "rename the resource address of a bucket with a moved block", "s3",
    bucket(i), bucket(i, addr="main") + moved("aws_s3_bucket.b", "aws_s3_bucket.main"), [objs(i)],
    [P("s3", n(i, "data"))])
i = 18
add(i, "stop managing a bucket with a removed block (destroy = false)", "s3",
    bucket(i, force=True), removed("aws_s3_bucket.b"), [objs(i)], [P("s3", n(i, "data"))])
i = 19
add(i, "remove a bucket holding objects; force_destroy = true; a second bucket stays", "s3",
    bucket(i, force=True) + bucket(i, addr="logs", name="logs", force=True), bucket(i, addr="logs", name="logs", force=True),
    [objs(i, "logs")], [P("s3", n(i, "logs"))])
i = 20
add(i, "replace a bucket by request (replace_triggered_by), force_destroy = true, objects inside", "s3",
    trigger("1") + bucket(i, force=True, life=("replace_triggered_by = [terraform_data.rev]",)),
    trigger("2") + bucket(i, force=True, life=("replace_triggered_by = [terraform_data.rev]",)),
    [objs(i)], [P("s3", n(i, "data"))])
i = 21
add(i, "add tags to a bucket holding objects", "s3",
    bucket(i), bucket(i, extra='  tags = { team = "data" }\n'), [objs(i)], [P("s3", n(i, "data"))])

# ================================================================ DynamoDB (200 items written by the app)
i = 22
add(i, "remove a table holding items", "ddb", table(i), "", [items(i)], [P("ddb", n(i, "items"))])
i = 23
add(i, "remove a table holding items with deletion protection on", "ddb",
    table(i, protect=True), "", [items(i)], [P("ddb", n(i, "items"))])
i = 24
add(i, "change the hash key of a table holding items", "ddb",
    table(i), table(i, hash_="id"), [items(i)], [P("ddb", n(i, "items"))])
i = 25
add(i, "change the hash key of an empty table", "ddb",
    table(i), table(i, hash_="id"), [], [P("ddb", n(i, "items"))])
i = 26
add(i, "change the hash key and turn deletion protection off in the same change", "ddb",
    table(i, protect=True), table(i, hash_="id", protect=False), [items(i)], [P("ddb", n(i, "items"))])
i = 27
add(i, "rename a table holding items", "ddb",
    table(i), table(i, name="items2"), [items(i)], [P("ddb", n(i, "items"))])
i = 28
add(i, "add a global secondary index to a table holding items", "ddb",
    table(i), table(i, attrs=[("email", "S")], extra='  global_secondary_index {\n    name = "by-email"\n'
                    '    hash_key = "email"\n    projection_type = "ALL"\n  }\n'), [items(i)], [P("ddb", n(i, "items"))])
i = 29
add(i, "switch a table holding items from provisioned to on-demand billing", "ddb",
    table(i, billing="PROVISIONED"), table(i), [items(i)], [P("ddb", n(i, "items"))])
i = 30
add(i, "enable a stream on a table holding items", "ddb",
    table(i), table(i, extra='  stream_enabled = true\n  stream_view_type = "NEW_AND_OLD_IMAGES"\n'), [items(i)],
    [P("ddb", n(i, "items"))])
i = 31
add(i, "add a range key to a table holding items", "ddb",
    table(i), table(i, range_=("sk", "S")), [items(i)], [P("ddb", n(i, "items"))])
i = 32
add(i, "change the hash key of a table holding items with create_before_destroy", "ddb",
    table(i, life=("create_before_destroy = true",)), table(i, hash_="id", life=("create_before_destroy = true",)),
    [items(i)], [P("ddb", n(i, "items"))])
i = 33
add(i, "turn deletion protection off on a table holding items (nothing else)", "ddb",
    table(i, protect=True), table(i, protect=False), [items(i)], [P("ddb", n(i, "items"))])
i = 34
add(i, "enable TTL on an attribute the items do not have", "ddb",
    table(i), table(i, extra='  ttl {\n    attribute_name = "expires_at"\n    enabled = true\n  }\n'), [items(i)],
    [P("ddb", n(i, "items"))])
i = 35
add(i, "change the hash key type of a table holding items (S to N)", "ddb",
    table(i), table(i, htype="N"), [items(i)], [P("ddb", n(i, "items"))])
i = 36
add(i, "raise the provisioned capacity of a table holding items", "ddb",
    table(i, billing="PROVISIONED"),
    table(i, billing="PROVISIONED").replace("read_capacity = 5", "read_capacity = 10"), [items(i)],
    [P("ddb", n(i, "items"))])
i = 37
add(i, "remove an empty table", "ddb", table(i), "", [], [P("ddb", n(i, "items"))])
i = 38
add(i, "stop managing a table with a removed block (destroy = false)", "ddb",
    table(i), removed("aws_dynamodb_table.t"), [items(i)], [P("ddb", n(i, "items"))])
i = 39
add(i, "replace a protected table by request (replace_triggered_by)", "ddb",
    trigger("1") + table(i, protect=True, life=("replace_triggered_by = [terraform_data.rev]",)),
    trigger("2") + table(i, protect=True, life=("replace_triggered_by = [terraform_data.rev]",)),
    [items(i)], [P("ddb", n(i, "items"))])

# ================================================================ SQS (30 messages waiting)
i = 40
add(i, "remove a queue with messages waiting", "sqs", queue(i), "", [msgs(i)], [P("sqs", n(i, "jobs"))])
i = 41
add(i, "rename a queue with messages waiting", "sqs", queue(i), queue(i, name="jobs2"), [msgs(i)],
    [P("sqs", n(i, "jobs"))])
i = 42
add(i, "rename an empty queue", "sqs", queue(i), queue(i, name="jobs2"), [], [P("sqs", n(i, "jobs"))])
i = 43
add(i, "change the visibility timeout of a queue with messages waiting", "sqs",
    queue(i), queue(i, extra="  visibility_timeout_seconds = 120\n"), [msgs(i)], [P("sqs", n(i, "jobs"))])
i = 44
add(i, "shorten message retention to 1 hour on a queue whose messages are minutes old", "sqs",
    queue(i), queue(i, extra="  message_retention_seconds = 3600\n"), [msgs(i)], [P("sqs", n(i, "jobs"))])
i = 45
add(i, "turn a standard queue with messages into a FIFO queue", "sqs",
    queue(i), queue(i, name="jobs.fifo", extra="  fifo_queue = true\n"), [msgs(i)], [P("sqs", n(i, "jobs"))])
i = 46
add(i, "add a dead-letter queue and redrive policy to a queue with messages", "sqs",
    queue(i), queue(i, addr="dlq", name="jobs-dlq") + queue(
        i, extra='  redrive_policy = jsonencode({ deadLetterTargetArn = aws_sqs_queue.dlq.arn, maxReceiveCount = 5 })\n'),
    [msgs(i)], [P("sqs", n(i, "jobs"))])
i = 47
add(i, "add a delivery delay to a queue with messages waiting", "sqs",
    queue(i), queue(i, extra="  delay_seconds = 30\n"), [msgs(i)], [P("sqs", n(i, "jobs"))])
i = 48
add(i, "rename a queue with messages waiting, with create_before_destroy", "sqs",
    queue(i, life=("create_before_destroy = true",)), queue(i, name="jobs2", life=("create_before_destroy = true",)),
    [msgs(i)], [P("sqs", n(i, "jobs"))])
i = 49
add(i, "stop managing a queue with a removed block (destroy = false)", "sqs",
    queue(i), removed("aws_sqs_queue.q"), [msgs(i)], [P("sqs", n(i, "jobs"))])
i = 50
add(i, "remove the dead-letter queue (holding failed messages) of a queue", "sqs",
    queue(i, addr="dlq", name="jobs-dlq") + queue(
        i, extra='  redrive_policy = jsonencode({ deadLetterTargetArn = aws_sqs_queue.dlq.arn, maxReceiveCount = 5 })\n'),
    queue(i), [msgs(i, "jobs-dlq")], [P("sqs", n(i, "jobs"))])

# ================================================================ SNS
i = 51
add(i, "rename a topic", "sns", topic(i), topic(i, name="events2"), [], [P("sns", n(i, "events"))])
i = 52
add(i, "change the display name of a topic", "sns", topic(i), topic(i, extra='  display_name = "Events"\n'), [],
    [P("sns", n(i, "events"))])
i = 53
add(i, "remove a topic and its queue subscription; the queue holds delivered messages", "sns",
    topic(i) + queue(i) + 'resource "aws_sns_topic_subscription" "sub" {\n  topic_arn = aws_sns_topic.tp.arn\n'
    '  protocol = "sqs"\n  endpoint = aws_sqs_queue.q.arn\n}\n', queue(i), [msgs(i)],
    [P("sns", n(i, "events")), P("sqs", n(i, "jobs"))])
i = 54
add(i, "subscribe a queue with messages to a topic", "sns",
    topic(i) + queue(i), topic(i) + queue(i) + 'resource "aws_sns_topic_subscription" "sub" {\n'
    '  topic_arn = aws_sns_topic.tp.arn\n  protocol = "sqs"\n  endpoint = aws_sqs_queue.q.arn\n}\n', [msgs(i)],
    [P("sns", n(i, "events")), P("sqs", n(i, "jobs"))])

# ================================================================ Secrets Manager (value written by the app)
i = 55
add(i, "remove a secret (recovery window not set)", "secret", secret(i), "", [secret_value(i)],
    [P("secret", n(i, "db-password"))])
i = 56
add(i, "remove a secret with recovery_window_in_days = 0", "secret", secret(i, window=0), "", [secret_value(i)],
    [P("secret", n(i, "db-password"))])
i = 57
add(i, "rename a secret (recovery window 7 days)", "secret", secret(i, window=7),
    secret(i, name="db-password2", window=7), [secret_value(i)], [P("secret", n(i, "db-password"))])
i = 58
add(i, "rename a secret with recovery_window_in_days = 0", "secret", secret(i, window=0),
    secret(i, name="db-password2", window=0), [secret_value(i)], [P("secret", n(i, "db-password"))])
i = 59
add(i, "replace a secret by request, same name, recovery window 7 days", "secret",
    trigger("1") + secret(i, window=7, life=("replace_triggered_by = [terraform_data.rev]",)),
    trigger("2") + secret(i, window=7, life=("replace_triggered_by = [terraform_data.rev]",)),
    [secret_value(i)], [P("secret", n(i, "db-password"))])
i = 60
add(i, "change the description of a secret", "secret", secret(i),
    secret(i, extra='  description = "primary database password"\n'), [secret_value(i)],
    [P("secret", n(i, "db-password"))])
i = 61
add(i, "set recovery_window_in_days = 0 on a secret (nothing else)", "secret", secret(i), secret(i, window=0),
    [secret_value(i)], [P("secret", n(i, "db-password"))])
i = 62
add(i, "managed secret version whose value the app rotated; configured value changed", "secret",
    secret(i) + 'resource "aws_secretsmanager_secret_version" "v" {\n  secret_id = aws_secretsmanager_secret.s.id\n'
    '  secret_string = "initial"\n}\n',
    secret(i) + 'resource "aws_secretsmanager_secret_version" "v" {\n  secret_id = aws_secretsmanager_secret.s.id\n'
    '  secret_string = "from-config-2"\n}\n', [secret_value(i)], [P("secret", n(i, "db-password"))])
i = 63
add(i, "remove the managed secret version (the app wrote a newer value)", "secret",
    secret(i) + 'resource "aws_secretsmanager_secret_version" "v" {\n  secret_id = aws_secretsmanager_secret.s.id\n'
    '  secret_string = "initial"\n}\n', secret(i), [secret_value(i)], [P("secret", n(i, "db-password"))])
i = 64
add(i, "rename a secret with create_before_destroy (recovery window not set)", "secret",
    secret(i, life=("create_before_destroy = true",)),
    secret(i, name="db-password2", life=("create_before_destroy = true",)), [secret_value(i)],
    [P("secret", n(i, "db-password"))])

# ================================================================ SSM parameters (value written by the app)
i = 65
add(i, "remove a parameter whose value the app manages (ignore_changes = [value])", "ssm",
    param(i), "", [ssm_value(i)], [P("ssm", f"/vaws/s{i}/app/endpoint")])
i = 66
add(i, "rename a parameter whose value the app manages", "ssm",
    param(i), param(i, name="app/endpoint-v2"), [ssm_value(i)], [P("ssm", f"/vaws/s{i}/app/endpoint")])
i = 67
add(i, "parameter value set in the config, the app changed it; config value changed", "ssm",
    param(i, ignore=False), param(i, ignore=False, value="https://api.internal/v2"), [ssm_value(i)],
    [P("ssm", f"/vaws/s{i}/app/endpoint")])
i = 68
add(i, "change the description of a parameter the app manages", "ssm",
    param(i), param(i, extra='  description = "API endpoint"\n'), [ssm_value(i)],
    [P("ssm", f"/vaws/s{i}/app/endpoint")])
i = 69
add(i, "change a parameter the app manages from String to SecureString", "ssm",
    param(i), param(i, typ="SecureString"), [ssm_value(i)], [P("ssm", f"/vaws/s{i}/app/endpoint")])
i = 70
add(i, "move a parameter the app manages from the Advanced tier to Standard", "ssm",
    param(i, extra='  tier = "Advanced"\n'), param(i, extra='  tier = "Standard"\n'), [ssm_value(i)],
    [P("ssm", f"/vaws/s{i}/app/endpoint")])
i = 71
add(i, "stop managing a parameter with a removed block (destroy = false)", "ssm",
    param(i), removed("aws_ssm_parameter.p"), [ssm_value(i)], [P("ssm", f"/vaws/s{i}/app/endpoint")])
i = 72
add(i, "parameter value in the config, app changed it, config unchanged (drift is overwritten)", "ssm",
    param(i, ignore=False), param(i, ignore=False), [ssm_value(i)], [P("ssm", f"/vaws/s{i}/app/endpoint")])

# ================================================================ Lambda (invoked by name)
i = 73
add(i, "rename a function", "lambda", role(i) + fn(i), role(i) + fn(i, name="worker2"), [],
    [P("lambda", n(i, "worker"))])
i = 74
add(i, "raise memory and timeout of a function", "lambda", role(i) + fn(i),
    role(i) + fn(i, extra="  memory_size = 256\n  timeout = 30\n"), [], [P("lambda", n(i, "worker"))])
i = 75
add(i, "remove a function", "lambda", role(i) + fn(i), role(i), [], [P("lambda", n(i, "worker"))])
i = 76
add(i, "add an environment variable to a function", "lambda", role(i) + fn(i),
    role(i) + fn(i, extra='  environment {\n    variables = { LOG_LEVEL = "debug" }\n  }\n'), [],
    [P("lambda", n(i, "worker"))])
i = 77
add(i, "change the runtime of a function (python3.12 to python3.13)", "lambda", role(i) + fn(i),
    role(i) + fn(i).replace("python3.12", "python3.13"), [], [P("lambda", n(i, "worker"))])
i = 78
add(i, "rename a function with create_before_destroy", "lambda", role(i) + fn(i, life=("create_before_destroy = true",)),
    role(i) + fn(i, name="worker2", life=("create_before_destroy = true",)), [], [P("lambda", n(i, "worker"))])

# ================================================================ IAM (no data; wider access is not labelled here)
i = 79
add(i, "widen a role's inline policy to all actions on all resources", "iam",
    role(i) + 'resource "aws_iam_role_policy" "p" {\n  role = aws_iam_role.r.id\n  name = "read"\n  policy = jsonencode('
    '{ Version = "2012-10-17", Statement = [{ Effect = "Allow", Action = "s3:GetObject", Resource = "*" }] })\n}\n',
    role(i) + 'resource "aws_iam_role_policy" "p" {\n  role = aws_iam_role.r.id\n  name = "read"\n  policy = jsonencode('
    '{ Version = "2012-10-17", Statement = [{ Effect = "Allow", Action = "*", Resource = "*" }] })\n}\n', [], [])
i = 80
add(i, "let any principal assume a role (trust policy Principal *)", "iam",
    role(i), role(i).replace('Service = "lambda.amazonaws.com"', 'AWS = "*"'), [], [])
i = 81
add(i, "a bucket holding objects and a queue with messages; only the queue's tags change", "mixed",
    bucket(i) + queue(i), bucket(i) + queue(i, extra='  tags = { team = "jobs" }\n'), [objs(i), msgs(i)],
    [P("s3", n(i, "data")), P("sqs", n(i, "jobs"))])
i = 82
add(i, "remove a bucket (force_destroy unset, objects) and a queue (messages) together", "mixed",
    queue(i) + bucket(i), "", [objs(i), msgs(i)], [P("s3", n(i, "data")), P("sqs", n(i, "jobs"))])
i = 83
add(i, "remove a protected table and an unprotected table, both holding items", "mixed",
    table(i, protect=True) + table(i, addr="t2", name="items2"), "", [items(i), items(i, "items2")],
    [P("ddb", n(i, "items")), P("ddb", n(i, "items2"))])
i = 84
add(i, "rename an empty bucket (force_destroy unset)", "s3", bucket(i), bucket(i, name="data2"), [],
    [P("s3", n(i, "data"))])

# ================================================================ provider-behaviour tests that prove the notes
FID = []


def fid(i, title, v1, v2, seed=(), probes=()):
    S.append(dict(id=i, title=title, family="fid", v1=v1, v2=v2, seed=list(seed), probes=list(probes), split="fid"))


fid(901, "fid: bucket with objects, force_destroy false, removed", bucket(901), "", [objs(901)],
    [P("s3", n(901, "data"))])
fid(902, "fid: versioned bucket with objects, force_destroy true, removed", bucket(902, force=True) + versioning(), "",
    [objs(902)], [P("s3", n(902, "data"))])
fid(903, "fid: force_destroy false -> true together with a forced replacement", bucket(903),
    bucket(903, name="other", force=True), [objs(903)], [P("s3", n(903, "data"))])
fid(904, "fid: protected table removed", table(904, protect=True), "", [items(904)], [P("ddb", n(904, "items"))])
fid(905, "fid: protected table, protection off + forced replacement in one change", table(905, protect=True),
    table(905, name="other", protect=False), [items(905)], [P("ddb", n(905, "items"))])
fid(906, "fid: table forced replacement (range key added)", table(906), table(906, range_=("sk", "S")), [items(906)],
    [P("ddb", n(906, "items"))])
fid(907, "fid: secret removed, window 7", secret(907, window=7), "", [secret_value(907)],
    [P("secret", n(907, "db-password"))])
fid(908, "fid: secret replaced by request, same name, window 7",
    trigger("1") + secret(908, window=7, life=("replace_triggered_by = [terraform_data.rev]",)),
    trigger("2") + secret(908, window=7, life=("replace_triggered_by = [terraform_data.rev]",)),
    [secret_value(908)], [P("secret", n(908, "db-password"))])
fid(909, "fid: s3 object drifted, unversioned, content changed", bucket(909) + s3_object(),
    bucket(909) + s3_object(content='{"mode": "z"}'), [{"op": "s3_put", "bucket": n(909, "data"), "key": "config/app.json"}],
    [P("s3", n(909, "data"))])
fid(910, "fid: s3 object drifted, versioned, config unchanged", bucket(910) + versioning() + s3_object(),
    bucket(910) + versioning() + s3_object(), [{"op": "s3_put", "bucket": n(910, "data"), "key": "config/app.json"}],
    [P("s3", n(910, "data"))])
fid(911, "fid: queue renamed, messages", queue(911), queue(911, name="other"), [msgs(911)], [P("sqs", n(911, "jobs"))])
fid(912, "fid: table forced replacement with create_before_destroy, same name", table(912, life=("create_before_destroy = true",)),
    table(912, hash_="id", life=("create_before_destroy = true",)), [items(912)], [P("ddb", n(912, "items"))])
fid(913, "fid: function code updated in place", role(913) + fn(913), role(913) + fn(913, zip_="fn2"), [],
    [P("lambda", n(913, "worker"))])
fid(914, "fid: secret version, app value, config value changed", secret(914) +
    'resource "aws_secretsmanager_secret_version" "v" {\n  secret_id = aws_secretsmanager_secret.s.id\n'
    '  secret_string = "a"\n}\n', secret(914) + 'resource "aws_secretsmanager_secret_version" "v" {\n'
    '  secret_id = aws_secretsmanager_secret.s.id\n  secret_string = "b"\n}\n', [secret_value(914)],
    [P("secret", n(914, "db-password"))])
fid(915, "fid: parameter value in config, app changed it, config changed", param(915, ignore=False),
    param(915, ignore=False, value="x2"), [ssm_value(915)], [P("ssm", "/vaws/s915/app/endpoint")])
fid(916, "fid: parameter renamed", param(916), param(916, name="other"), [ssm_value(916)],
    [P("ssm", "/vaws/s916/app/endpoint")])
fid(917, "fid: secret removed, window 0", secret(917, window=0), "", [secret_value(917)],
    [P("secret", n(917, "db-password"))])

BY_ID = {s["id"]: s for s in S}

fid(918, "fid: s3 object drifted, versioned, content changed", bucket(918) + versioning() + s3_object(),
    bucket(918) + versioning() + s3_object(content='{"mode": "z"}'),
    [{"op": "s3_put", "bucket": n(918, "data"), "key": "config/app.json"}], [P("s3", n(918, "data"))])
fid(919, "fid: topic with a queue subscription removed", topic(919) + queue(919) +
    'resource "aws_sns_topic_subscription" "sub" {\n  topic_arn = aws_sns_topic.tp.arn\n  protocol = "sqs"\n'
    '  endpoint = aws_sqs_queue.q.arn\n}\n', queue(919), [msgs(919)], [P("sns", n(919, "events")), P("sqs", n(919, "jobs"))])
BY_ID = {s["id"]: s for s in S}
