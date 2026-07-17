resource "aws_glue_catalog_database" "historical" {
  name        = replace("${local.name_prefix}-historical", "-", "_")
  description = "Versioned, point-in-time NRFI/YRFI historical datasets"
}

resource "aws_athena_workgroup" "historical" {
  name          = "${local.name_prefix}-historical"
  force_destroy = false

  configuration {
    enforce_workgroup_configuration    = true
    publish_cloudwatch_metrics_enabled = true
    bytes_scanned_cutoff_per_query     = 10737418240

    result_configuration {
      output_location = "s3://${aws_s3_bucket.lake.id}/athena-results/"

      encryption_configuration {
        encryption_option = "SSE_KMS"
        kms_key_arn       = aws_kms_key.platform.arn
      }
    }
  }
}

data "aws_iam_policy_document" "sagemaker_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["sagemaker.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "sagemaker_training" {
  name               = "${local.name_prefix}-sagemaker-training"
  assume_role_policy = data.aws_iam_policy_document.sagemaker_assume.json
}

data "aws_iam_policy_document" "sagemaker_training" {
  statement {
    sid       = "ListApprovedDataBuckets"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.raw.arn, aws_s3_bucket.lake.arn, aws_s3_bucket.evidence.arn]
  }

  statement {
    sid = "ReadTrainingInputs"
    actions = [
      "s3:GetObject",
      "s3:GetObjectVersion",
    ]
    resources = [
      "${aws_s3_bucket.raw.arn}/*",
      "${aws_s3_bucket.lake.arn}/normalized/*",
      "${aws_s3_bucket.lake.arn}/features/*",
      "${aws_s3_bucket.lake.arn}/manifests/*",
    ]
  }

  statement {
    sid = "WriteModelAndEvaluationArtifacts"
    actions = [
      "s3:GetObject",
      "s3:GetObjectVersion",
      "s3:PutObject",
      "s3:PutObjectRetention",
      "s3:PutObjectTagging",
    ]
    resources = [
      "${aws_s3_bucket.lake.arn}/models/*",
      "${aws_s3_bucket.lake.arn}/calibrators/*",
      "${aws_s3_bucket.lake.arn}/predictions/*",
      "${aws_s3_bucket.evidence.arn}/*",
    ]
  }

  statement {
    sid = "ReadImmutableContainer"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer",
    ]
    resources = [aws_ecr_repository.pipeline.arn]
  }

  statement {
    sid       = "AuthorizeContainerRegistry"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid = "PublishTrainingLogs"
    actions = [
      "cloudwatch:PutMetricData",
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:DescribeLogStreams",
      "logs:PutLogEvents",
    ]
    resources = ["*"]
  }

  statement {
    sid = "UsePlatformKey"
    actions = [
      "kms:Decrypt",
      "kms:DescribeKey",
      "kms:Encrypt",
      "kms:GenerateDataKey",
      "kms:ReEncryptFrom",
      "kms:ReEncryptTo",
    ]
    resources = [aws_kms_key.platform.arn]
  }

  statement {
    sid       = "DenyLockedHoldout"
    effect    = "Deny"
    actions   = ["s3:*", "kms:Decrypt", "kms:GenerateDataKey"]
    resources = [aws_s3_bucket.holdout.arn, "${aws_s3_bucket.holdout.arn}/*", aws_kms_key.holdout.arn]
  }
}

resource "aws_iam_role_policy" "sagemaker_training" {
  name   = "${local.name_prefix}-training-data-boundary"
  role   = aws_iam_role.sagemaker_training.id
  policy = data.aws_iam_policy_document.sagemaker_training.json
}

resource "aws_sagemaker_model_package_group" "candidates" {
  model_package_group_name        = "${local.name_prefix}-candidates"
  model_package_group_description = "Chronologically evaluated probability-model candidates; registration does not imply approval"
}
