"""How these AWS resources and the provider behave: one sentence each, added only when a change in the plan needs it.
Every note was VERIFIED BY EXECUTION in LocalStack Community 4.14.0 with hashicorp/aws 6.68.0 before it was written;
PROOF lists the provider-behaviour scenarios (scenarios.py, split "fid", results in runs/s9xx/) that prove it.
None of them is a scenario of the dev or test set."""
from __future__ import annotations

BUCKET_DESTROY = ("Destroying an aws_s3_bucket that still holds objects or object versions fails unless force_destroy "
                  "is true in the current state; a force_destroy = true set in the same plan does not apply to that "
                  "destroy. With force_destroy = true in the state, every object and every version is deleted first.")
OBJECT_WRITE = ("An aws_s3_object whose configured content changes is written again over the object at that key; in a "
                "bucket with versioning enabled the content it replaces stays as a noncurrent version, otherwise it is "
                "gone.")
TABLE_DESTROY = ("Destroying an aws_dynamodb_table whose deletion protection is on fails, also when the same plan "
                 "turns protection off for its replacement. A table created by a replacement starts empty: items are "
                 "not copied. Creating a table whose name is already taken fails.")
QUEUE_DESTROY = ("Destroying an SQS queue deletes the messages waiting in it; a queue created by a replacement or "
                 "under a new name starts empty.")
SECRET_DESTROY = ("Destroying an aws_secretsmanager_secret schedules it for deletion after the recovery_window_in_days "
                  "in the current state (30 when unset): until then its value cannot be read, the secret can be "
                  "restored, and no new secret with the same name can be created. With 0 it is deleted at once, for "
                  "good.")
SECRET_VERSION = ("Writing a secret version makes it AWSCURRENT and labels the version that was current AWSPREVIOUS, "
                  "which can still be read.")
PARAMETER = ("Updating an SSM parameter's value keeps its earlier values in its history; destroying a parameter, also "
             "when it is replaced under a new name, deletes it together with its history.")
FUNCTION = "Updating a Lambda function in place keeps it invokable by its name throughout."
TOPIC = "Destroying an SNS topic deletes its subscriptions; the subscribed queue and its messages are kept."

PROOF = {
    BUCKET_DESTROY: [901, 902, 903],
    OBJECT_WRITE: [909, 918],
    TABLE_DESTROY: [904, 905, 906, 912],
    QUEUE_DESTROY: [911],
    SECRET_DESTROY: [907, 908, 917],
    SECRET_VERSION: [914],
    PARAMETER: [915, 916],
    FUNCTION: [913],
    TOPIC: [919],
}


def changes(plan):
    return [rc for rc in plan.get("resource_changes") or [] if rc["mode"] == "managed"
            and rc["change"]["actions"] not in (["no-op"], ["read"])]


def notes_for(plan):
    out = []
    rcs = changes(plan)
    acts = {(rc["type"], a) for rc in rcs for a in rc["change"]["actions"]}

    def add(n):
        if n not in out:
            out.append(n)

    if ("aws_s3_bucket", "delete") in acts:
        add(BUCKET_DESTROY)
    if ("aws_s3_object", "update") in acts or ("aws_s3_object", "create") in acts:
        add(OBJECT_WRITE)
    if ("aws_dynamodb_table", "delete") in acts or ("aws_dynamodb_table", "create") in acts:
        add(TABLE_DESTROY)
    if ("aws_sqs_queue", "delete") in acts:
        add(QUEUE_DESTROY)
    if ("aws_secretsmanager_secret", "delete") in acts:
        add(SECRET_DESTROY)
    if any(t == "aws_secretsmanager_secret_version" for t, _ in acts):
        add(SECRET_VERSION)
    if any(t == "aws_ssm_parameter" for t, _ in acts):
        add(PARAMETER)
    if ("aws_lambda_function", "update") in acts:
        add(FUNCTION)
    if ("aws_sns_topic", "delete") in acts:
        add(TOPIC)
    return out
