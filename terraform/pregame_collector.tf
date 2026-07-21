locals {
  pregame_collector_name  = "${local.name_prefix}-pregame-collector"
  pregame_forward_prefix  = "signals/pregame/official-statsapi/forward"
  pregame_lineup_prefix   = "signals/pregame/official-statsapi/lineups"
  pregame_assembly_prefix = "signals/pregame/assembly"
  # Live assembly now uses the reproduced, determinism-verified 2015-2024
  # profile projection. The prior 2021-2024 key is retained as the rollback
  # target (its read grant is preserved) so reverting is a one-line change.
  pitcher_profiles_key          = "features/pitcher-statcast-strict-prior-2015-2024-v1/profiles.jsonl"
  pitcher_profiles_rollback_key = "features/pitcher-statcast-strict-prior-v1/profiles.jsonl"
  # Compact terminal batter projection (~9.46 MB) that the assembly loads and
  # verifies (identity 7e7fc570, 2606 rows, 1543 eligible). NOT the 1.7 GB
  # historical projection. Omitting the env var reverts to pitcher-only assembly.
  terminal_batter_profiles_key = "features/batter-statcast-strict-prior-2015-2024-v1/terminal_batter_profiles.jsonl"
}

data "archive_file" "pregame_collector" {
  type        = "zip"
  output_path = "${path.module}/.terraform/pregame-collector.zip"

  source {
    content  = file("${path.module}/../nrfi/__init__.py")
    filename = "nrfi/__init__.py"
  }

  source {
    content  = file("${path.module}/../nrfi/pregame_snapshot.py")
    filename = "nrfi/pregame_snapshot.py"
  }

  source {
    content  = file("${path.module}/../nrfi/forward_admission.py")
    filename = "nrfi/forward_admission.py"
  }

  source {
    content  = file("${path.module}/../nrfi/lineup_snapshot.py")
    filename = "nrfi/lineup_snapshot.py"
  }

  source {
    content  = file("${path.module}/../nrfi/lineup_admission.py")
    filename = "nrfi/lineup_admission.py"
  }

  source {
    content  = file("${path.module}/../nrfi/batter_profile_loader.py")
    filename = "nrfi/batter_profile_loader.py"
  }

  source {
    content  = file("${path.module}/../nrfi/batter_top_of_order.py")
    filename = "nrfi/batter_top_of_order.py"
  }

  source {
    content  = file("${path.module}/../nrfi/batter_eligibility.py")
    filename = "nrfi/batter_eligibility.py"
  }

  source {
    content  = file("${path.module}/../nrfi/aws_pregame_collector.py")
    filename = "nrfi/aws_pregame_collector.py"
  }
}

data "aws_iam_policy_document" "pregame_collector_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "pregame_collector" {
  name               = local.pregame_collector_name
  assume_role_policy = data.aws_iam_policy_document.pregame_collector_assume.json
}

data "aws_iam_policy_document" "pregame_collector" {
  statement {
    sid     = "WriteForwardSnapshotsAndAssemblies"
    actions = ["s3:PutObject"]
    resources = [
      "${aws_s3_bucket.lake.arn}/${local.pregame_forward_prefix}/*",
      "${aws_s3_bucket.lake.arn}/${local.pregame_lineup_prefix}/*",
      "${aws_s3_bucket.lake.arn}/${local.pregame_assembly_prefix}/*",
    ]
  }

  statement {
    sid     = "ReadForwardSnapshotsAndProfiles"
    actions = ["s3:GetObject"]
    resources = [
      "${aws_s3_bucket.lake.arn}/${local.pregame_forward_prefix}/*",
      "${aws_s3_bucket.lake.arn}/${local.pregame_lineup_prefix}/*",
      "${aws_s3_bucket.lake.arn}/${local.pitcher_profiles_key}",
      "${aws_s3_bucket.lake.arn}/${local.pitcher_profiles_rollback_key}",
      "${aws_s3_bucket.lake.arn}/${local.terminal_batter_profiles_key}",
    ]
  }

  statement {
    sid       = "ListForwardSnapshots"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.lake.arn]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values = [
        "${local.pregame_forward_prefix}/*",
        "${local.pregame_lineup_prefix}/*",
      ]
    }
  }

  statement {
    sid = "EncryptForwardSnapshotsViaS3"
    actions = [
      "kms:GenerateDataKey*",
      "kms:Encrypt",
      "kms:Decrypt",
      "kms:DescribeKey",
    ]
    resources = [
      aws_kms_key.platform.arn,
    ]

    condition {
      test     = "StringEquals"
      variable = "kms:CallerAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }

    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["s3.${var.aws_region}.amazonaws.com"]
    }
  }

  statement {
    sid = "WriteBoundedLambdaLogs"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["${aws_cloudwatch_log_group.pregame_collector.arn}:*"]
  }

  statement {
    sid     = "DenyLockedHoldoutStorage"
    effect  = "Deny"
    actions = ["s3:*"]
    resources = [
      "arn:${data.aws_partition.current.partition}:s3:::*locked-holdout*",
      "arn:${data.aws_partition.current.partition}:s3:::*locked-holdout*/*",
    ]
  }

  statement {
    sid       = "DenyLockedHoldoutKeys"
    effect    = "Deny"
    actions   = ["kms:Decrypt", "kms:GenerateDataKey*"]
    resources = ["*"]

    condition {
      test     = "ForAnyValue:StringLike"
      variable = "kms:ResourceAliases"
      values   = ["alias/*locked-holdout*"]
    }
  }
}

resource "aws_iam_role_policy" "pregame_collector" {
  name   = "${local.pregame_collector_name}-boundary"
  role   = aws_iam_role.pregame_collector.id
  policy = data.aws_iam_policy_document.pregame_collector.json
}

resource "aws_cloudwatch_log_group" "pregame_collector" {
  name              = "/aws/lambda/${local.pregame_collector_name}"
  retention_in_days = var.operational_log_retention_days
}

resource "aws_lambda_function" "pregame_collector" {
  function_name = local.pregame_collector_name
  description   = "Immutable timestamped probable-starter snapshot collector"
  role          = aws_iam_role.pregame_collector.arn
  handler       = "nrfi.aws_pregame_collector.lambda_handler"
  runtime       = "python3.11"
  architectures = ["x86_64"]

  filename         = data.archive_file.pregame_collector.output_path
  source_code_hash = data.archive_file.pregame_collector.output_base64sha256

  # Sized for the 80.7 MB expanded 2015-2024 strict-prior profile projection.
  # Runtime emits staged eligibility (pregame_game_assembly.v3).
  memory_size = 1536
  timeout     = 120

  environment {
    variables = {
      NRFI_LAKE_BUCKET                      = aws_s3_bucket.lake.id
      NRFI_PLATFORM_KMS_KEY_ARN             = aws_kms_key.platform.arn
      NRFI_LOCKED_HOLDOUT_ACCESS            = "DENIED"
      NRFI_PITCHER_PROFILES_KEY             = local.pitcher_profiles_key
      NRFI_ASSEMBLY_FRESHNESS_SECONDS       = "21600"
      NRFI_TERMINAL_BATTER_PROFILES_KEY     = local.terminal_batter_profiles_key
      NRFI_TERMINAL_BATTER_PROFILES_SHA256  = "5ce26a4a87b66ea4a34b150a07e0ac53eb1303e27d9ef4b65ca1e9ab87a86be2"
      NRFI_TERMINAL_BATTER_PROFILE_IDENTITY = "7e7fc570d5ad4ea58fc087a87a488f54c63a07e729ae532ace1fd20e37f97299"
      NRFI_TERMINAL_BATTER_PROFILE_ROWS     = "2606"
      NRFI_TERMINAL_BATTER_PROFILE_ELIGIBLE = "1543"
    }
  }

  lifecycle {
    precondition {
      condition = alltrue([
        for prefix in [
          local.pregame_forward_prefix,
          local.pregame_lineup_prefix,
          local.pregame_assembly_prefix,
          local.pitcher_profiles_key,
          local.terminal_batter_profiles_key,
        ] :
        !strcontains(lower(prefix), "holdout") && !strcontains(prefix, "2025")
      ])
      error_message = "Pregame signal prefixes must remain outside locked-holdout storage."
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.pregame_collector,
    aws_iam_role_policy.pregame_collector,
  ]
}

resource "aws_cloudwatch_event_rule" "pregame_collector" {
  name                = "${local.pregame_collector_name}-schedule"
  description         = "Multiple pre-first-pitch probable-starter snapshots each day"
  schedule_expression = "cron(3 11,13,15,17,19,21,23,1 * * ? *)"
}

resource "aws_cloudwatch_event_target" "pregame_collector" {
  rule      = aws_cloudwatch_event_rule.pregame_collector.name
  target_id = "${local.pregame_collector_name}-lambda"
  arn       = aws_lambda_function.pregame_collector.arn
}

resource "aws_lambda_permission" "pregame_collector_events" {
  statement_id  = "AllowScheduledInvocation"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.pregame_collector.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.pregame_collector.arn
}
