locals {
  probability_api_name     = "${local.name_prefix}-probability-api"
  probability_response_key = "signals/sanitized/current/probability-response.json"
}

data "archive_file" "probability_api" {
  type        = "zip"
  output_path = "${path.module}/.terraform/probability-api.zip"

  source {
    content  = file("${path.module}/../nrfi/aws_probability_api.py")
    filename = "aws_probability_api.py"
  }
}

resource "aws_s3_object" "probability_response" {
  bucket                 = aws_s3_bucket.lake.id
  key                    = local.probability_response_key
  source                 = "${path.module}/assets/probability-response.json"
  source_hash            = filesha256("${path.module}/assets/probability-response.json")
  content_type           = "application/json"
  cache_control          = "no-store"
  server_side_encryption = "aws:kms"
  kms_key_id             = aws_kms_key.platform.arn

  lifecycle {
    precondition {
      condition = (
        !strcontains(lower(local.probability_response_key), "holdout") &&
        !strcontains(local.probability_response_key, "2025")
      )
      error_message = "The probability response key must remain outside locked-holdout storage."
    }
  }
}

data "aws_iam_policy_document" "probability_api_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "probability_api" {
  name               = "${local.name_prefix}-probability-api"
  assume_role_policy = data.aws_iam_policy_document.probability_api_assume.json
}

data "aws_iam_policy_document" "probability_api" {
  statement {
    sid       = "ReadSanitizedProbabilityResponse"
    actions   = ["s3:GetObject", "s3:GetObjectVersion"]
    resources = ["${aws_s3_bucket.lake.arn}/${local.probability_response_key}"]
  }

  statement {
    sid     = "DecryptSanitizedProbabilityResponse"
    actions = ["kms:Decrypt", "kms:DescribeKey"]
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
    resources = ["${aws_cloudwatch_log_group.probability_api.arn}:*"]
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

resource "aws_iam_role_policy" "probability_api" {
  name   = "${local.name_prefix}-probability-api-boundary"
  role   = aws_iam_role.probability_api.id
  policy = data.aws_iam_policy_document.probability_api.json
}

resource "aws_cloudwatch_log_group" "probability_api" {
  name              = "/aws/lambda/${local.probability_api_name}"
  retention_in_days = var.operational_log_retention_days
}

resource "aws_lambda_function" "probability_api" {
  function_name = local.probability_api_name
  description   = "Fail-closed sanitized NRFI/YRFI probability response"
  role          = aws_iam_role.probability_api.arn
  handler       = "aws_probability_api.lambda_handler"
  runtime       = "python3.11"
  architectures = ["x86_64"]

  filename         = data.archive_file.probability_api.output_path
  source_code_hash = data.archive_file.probability_api.output_base64sha256

  memory_size = 128
  timeout     = 10

  environment {
    variables = {
      NRFI_LAKE_BUCKET           = aws_s3_bucket.lake.id
      NRFI_LOCKED_HOLDOUT_ACCESS = "DENIED"
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.probability_api,
    aws_iam_role_policy.probability_api,
    aws_s3_object.probability_response,
  ]
}

resource "aws_lambda_function_url" "probability_api" {
  function_name      = aws_lambda_function.probability_api.function_name
  authorization_type = "AWS_IAM"
  invoke_mode        = "BUFFERED"
}
