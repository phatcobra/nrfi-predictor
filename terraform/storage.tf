locals {
  bucket_prefix = "${substr(local.name_prefix, 0, 25)}-${data.aws_caller_identity.current.account_id}-${var.aws_region}"
  buckets = {
    raw      = aws_s3_bucket.raw
    lake     = aws_s3_bucket.lake
    evidence = aws_s3_bucket.evidence
    logs     = aws_s3_bucket.logs
    holdout  = aws_s3_bucket.holdout
  }
  non_holdout_buckets = {
    raw      = aws_s3_bucket.raw
    lake     = aws_s3_bucket.lake
    evidence = aws_s3_bucket.evidence
    logs     = aws_s3_bucket.logs
  }
}

resource "aws_kms_key" "platform" {
  description             = "NRFI probability platform data, models, and evidence"
  enable_key_rotation     = true
  deletion_window_in_days = 30
}

resource "aws_kms_alias" "platform" {
  name          = "alias/${local.name_prefix}-platform"
  target_key_id = aws_kms_key.platform.key_id
}

resource "aws_kms_key" "holdout" {
  description             = "Separately protected locked-holdout evidence"
  enable_key_rotation     = true
  deletion_window_in_days = 30
}

resource "aws_kms_alias" "holdout" {
  name          = "alias/${local.name_prefix}-locked-holdout"
  target_key_id = aws_kms_key.holdout.key_id
}

resource "aws_s3_bucket" "raw" {
  bucket              = "${local.bucket_prefix}-raw"
  force_destroy       = false
  object_lock_enabled = true
}

resource "aws_s3_bucket" "lake" {
  bucket        = "${local.bucket_prefix}-lake"
  force_destroy = false
}

resource "aws_s3_bucket" "evidence" {
  bucket              = "${local.bucket_prefix}-evidence"
  force_destroy       = false
  object_lock_enabled = true
}

resource "aws_s3_bucket" "logs" {
  bucket        = "${local.bucket_prefix}-logs"
  force_destroy = false
}

resource "aws_s3_bucket" "holdout" {
  bucket              = "${local.bucket_prefix}-locked-holdout"
  force_destroy       = false
  object_lock_enabled = true
}

resource "aws_s3_bucket_versioning" "all" {
  for_each = local.buckets
  bucket   = each.value.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "all" {
  for_each = local.buckets
  bucket   = each.value.id

  rule {
    apply_server_side_encryption_by_default {
      kms_master_key_id = each.key == "holdout" ? aws_kms_key.holdout.arn : aws_kms_key.platform.arn
      sse_algorithm     = "aws:kms"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "all" {
  for_each = local.buckets
  bucket   = each.value.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "all" {
  for_each = local.buckets
  bucket   = each.value.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_object_lock_configuration" "raw" {
  bucket = aws_s3_bucket.raw.id

  rule {
    default_retention {
      mode = "GOVERNANCE"
      days = var.evidence_retention_days
    }
  }

  depends_on = [aws_s3_bucket_versioning.all]
}

resource "aws_s3_bucket_object_lock_configuration" "evidence" {
  bucket = aws_s3_bucket.evidence.id

  rule {
    default_retention {
      mode = "GOVERNANCE"
      days = var.evidence_retention_days
    }
  }

  depends_on = [aws_s3_bucket_versioning.all]
}

resource "aws_s3_bucket_object_lock_configuration" "holdout" {
  bucket = aws_s3_bucket.holdout.id

  rule {
    default_retention {
      mode = "GOVERNANCE"
      days = var.holdout_retention_days
    }
  }

  depends_on = [aws_s3_bucket_versioning.all]
}

resource "aws_s3_bucket_lifecycle_configuration" "durable" {
  for_each = {
    raw      = aws_s3_bucket.raw
    lake     = aws_s3_bucket.lake
    evidence = aws_s3_bucket.evidence
    holdout  = aws_s3_bucket.holdout
  }
  bucket = each.value.id

  rule {
    id     = "abort-incomplete-multipart-uploads"
    status = "Enabled"

    filter {}

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }

  depends_on = [aws_s3_bucket_versioning.all]
}

resource "aws_s3_bucket_lifecycle_configuration" "logs" {
  bucket = aws_s3_bucket.logs.id

  rule {
    id     = "expire-operational-logs"
    status = "Enabled"

    filter {}

    expiration {
      days = var.operational_log_retention_days
    }

    noncurrent_version_expiration {
      noncurrent_days = var.operational_log_retention_days
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }

  depends_on = [aws_s3_bucket_versioning.all]
}

data "aws_iam_policy_document" "bucket_transport" {
  for_each = local.non_holdout_buckets

  statement {
    sid     = "DenyInsecureTransport"
    effect  = "Deny"
    actions = ["s3:*"]
    resources = [
      each.value.arn,
      "${each.value.arn}/*",
    ]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "bucket_transport" {
  for_each = local.non_holdout_buckets
  bucket   = each.value.id
  policy   = data.aws_iam_policy_document.bucket_transport[each.key].json
}

data "aws_iam_policy_document" "holdout" {
  statement {
    sid     = "DenyInsecureTransport"
    effect  = "Deny"
    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.holdout.arn,
      "${aws_s3_bucket.holdout.arn}/*",
    ]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }

  statement {
    sid     = "DenyTrainingAndInferenceRoles"
    effect  = "Deny"
    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.holdout.arn,
      "${aws_s3_bucket.holdout.arn}/*",
    ]

    principals {
      type = "AWS"
      identifiers = [
        aws_iam_role.batch_job.arn,
        aws_iam_role.sagemaker_training.arn,
      ]
    }
  }
}

resource "aws_s3_bucket_policy" "holdout" {
  bucket = aws_s3_bucket.holdout.id
  policy = data.aws_iam_policy_document.holdout.json
}
