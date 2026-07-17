resource "aws_ecr_repository" "pipeline" {
  name                 = "${local.name_prefix}-pipeline"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = false

  encryption_configuration {
    encryption_type = "KMS"
    kms_key         = aws_kms_key.platform.arn
  }

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "pipeline" {
  repository = aws_ecr_repository.pipeline.name
  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Retain the newest 20 immutable release images"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = 20
        }
        action = {
          type = "expire"
        }
      }
    ]
  })
}

locals {
  private_interface_endpoint_services = toset([
    "ecr.api",
    "ecr.dkr",
    "logs",
  ])
}

resource "aws_subnet" "batch_private" {
  vpc_id                  = data.aws_vpc.default.id
  cidr_block              = var.private_subnet_cidr
  availability_zone       = var.private_subnet_availability_zone
  map_public_ip_on_launch = false

  tags = {
    Name = "${local.name_prefix}-batch-private"
  }

  lifecycle {
    precondition {
      condition     = data.aws_vpc.default.cidr_block == "172.31.0.0/16"
      error_message = "The verified us-east-2 default VPC CIDR has changed; review the private subnet before deployment."
    }
  }
}

resource "aws_route_table" "batch_private" {
  vpc_id = data.aws_vpc.default.id

  tags = {
    Name = "${local.name_prefix}-batch-private"
  }
}

resource "aws_route_table_association" "batch_private" {
  subnet_id      = aws_subnet.batch_private.id
  route_table_id = aws_route_table.batch_private.id
}

resource "aws_security_group" "batch_tasks" {
  name        = "${local.name_prefix}-batch-tasks"
  description = "No-ingress security group for the private baseline replay task"
  vpc_id      = data.aws_vpc.default.id

  tags = {
    Name = "${local.name_prefix}-batch-tasks"
  }
}

resource "aws_security_group" "interface_endpoints" {
  name        = "${local.name_prefix}-interface-endpoints"
  description = "HTTPS from the private baseline replay task only"
  vpc_id      = data.aws_vpc.default.id

  tags = {
    Name = "${local.name_prefix}-interface-endpoints"
  }
}

resource "aws_vpc_security_group_ingress_rule" "interface_https" {
  security_group_id            = aws_security_group.interface_endpoints.id
  referenced_security_group_id = aws_security_group.batch_tasks.id
  from_port                    = 443
  ip_protocol                  = "tcp"
  to_port                      = 443
}

resource "aws_vpc_security_group_egress_rule" "interface_https" {
  security_group_id            = aws_security_group.batch_tasks.id
  referenced_security_group_id = aws_security_group.interface_endpoints.id
  from_port                    = 443
  ip_protocol                  = "tcp"
  to_port                      = 443
}

resource "aws_vpc_security_group_egress_rule" "dns_udp" {
  security_group_id = aws_security_group.batch_tasks.id
  cidr_ipv4         = data.aws_vpc.default.cidr_block
  from_port         = 53
  ip_protocol       = "udp"
  to_port           = 53
}

resource "aws_vpc_security_group_egress_rule" "dns_tcp" {
  security_group_id = aws_security_group.batch_tasks.id
  cidr_ipv4         = data.aws_vpc.default.cidr_block
  from_port         = 53
  ip_protocol       = "tcp"
  to_port           = 53
}

resource "aws_vpc_endpoint" "s3" {
  vpc_id            = data.aws_vpc.default.id
  service_name      = "com.amazonaws.${var.aws_region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.batch_private.id]

  tags = {
    Name = "${local.name_prefix}-s3"
  }
}

resource "aws_vpc_security_group_egress_rule" "s3_https" {
  security_group_id = aws_security_group.batch_tasks.id
  prefix_list_id    = aws_vpc_endpoint.s3.prefix_list_id
  from_port         = 443
  ip_protocol       = "tcp"
  to_port           = 443
}

resource "aws_vpc_endpoint" "private_interface" {
  for_each = local.private_interface_endpoint_services

  vpc_id              = data.aws_vpc.default.id
  service_name        = "com.amazonaws.${var.aws_region}.${each.value}"
  vpc_endpoint_type   = "Interface"
  private_dns_enabled = true
  subnet_ids          = [aws_subnet.batch_private.id]
  security_group_ids  = [aws_security_group.interface_endpoints.id]

  tags = {
    Name = "${local.name_prefix}-${replace(each.value, ".", "-")}"
  }
}

data "aws_iam_policy_document" "batch_service_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["batch.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "batch_service" {
  name               = "${local.name_prefix}-batch-service"
  assume_role_policy = data.aws_iam_policy_document.batch_service_assume.json
}

resource "aws_iam_role_policy_attachment" "batch_service" {
  role       = aws_iam_role.batch_service.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/service-role/AWSBatchServiceRole"
}

data "aws_iam_policy_document" "ecs_tasks_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "batch_execution" {
  name               = "${local.name_prefix}-batch-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

resource "aws_iam_role_policy_attachment" "batch_execution" {
  role       = aws_iam_role.batch_execution.name
  policy_arn = "arn:${data.aws_partition.current.partition}:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role" "batch_job" {
  name               = "${local.name_prefix}-batch-job"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

data "aws_iam_policy_document" "batch_job" {
  statement {
    sid       = "ReadAdmittedRawObjects"
    actions   = ["s3:GetObject", "s3:GetObjectVersion"]
    resources = ["${aws_s3_bucket.raw.arn}/*"]
  }

  statement {
    sid       = "ListAdmittedRawAndLake"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.raw.arn, aws_s3_bucket.lake.arn]
  }

  statement {
    sid = "ReadWriteVersionedLakeObjects"
    actions = [
      "s3:GetObject",
      "s3:GetObjectVersion",
      "s3:PutObject",
      "s3:PutObjectTagging",
    ]
    resources = ["${aws_s3_bucket.lake.arn}/*"]
  }

  statement {
    sid = "WriteImmutableEvidence"
    actions = [
      "s3:GetObject",
      "s3:GetObjectVersion",
      "s3:PutObject",
      "s3:PutObjectRetention",
      "s3:PutObjectTagging",
    ]
    resources = ["${aws_s3_bucket.evidence.arn}/*"]
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

resource "aws_iam_role_policy" "batch_job" {
  name   = "${local.name_prefix}-batch-data-boundary"
  role   = aws_iam_role.batch_job.id
  policy = data.aws_iam_policy_document.batch_job.json
}

resource "aws_cloudwatch_log_group" "batch" {
  name              = "/aws/batch/${local.name_prefix}"
  retention_in_days = var.operational_log_retention_days
}

resource "aws_batch_compute_environment" "baseline" {
  count = var.enable_batch ? 1 : 0

  compute_environment_name = "${local.name_prefix}-fargate"
  type                     = "MANAGED"
  state                    = "ENABLED"
  service_role             = aws_iam_role.batch_service.arn

  compute_resources {
    max_vcpus          = var.batch_max_vcpus
    security_group_ids = [aws_security_group.batch_tasks.id]
    subnets            = [aws_subnet.batch_private.id]
    type               = "FARGATE"
  }

  depends_on = [aws_iam_role_policy_attachment.batch_service]
}

resource "aws_batch_job_queue" "baseline" {
  count = var.enable_batch ? 1 : 0

  name     = "${local.name_prefix}-baseline"
  state    = "ENABLED"
  priority = 1

  compute_environment_order {
    order               = 1
    compute_environment = aws_batch_compute_environment.baseline[0].arn
  }
}

resource "aws_batch_job_definition" "baseline" {
  count = var.enable_batch ? 1 : 0

  name                  = "${local.name_prefix}-baseline-replay"
  type                  = "container"
  platform_capabilities = ["FARGATE"]
  propagate_tags        = true

  container_properties = jsonencode({
    image            = "${aws_ecr_repository.pipeline.repository_url}:${var.batch_image_tag}"
    executionRoleArn = aws_iam_role.batch_execution.arn
    jobRoleArn       = aws_iam_role.batch_job.arn
    fargatePlatformConfiguration = {
      platformVersion = "LATEST"
    }
    networkConfiguration = {
      assignPublicIp = "DISABLED"
    }
    resourceRequirements = [
      {
        type  = "VCPU"
        value = tostring(var.batch_job_vcpus)
      },
      {
        type  = "MEMORY"
        value = tostring(var.batch_job_memory_mib)
      },
    ]
    environment = [
      {
        name  = "NRFI_RAW_BUCKET"
        value = aws_s3_bucket.raw.id
      },
      {
        name  = "NRFI_LAKE_BUCKET"
        value = aws_s3_bucket.lake.id
      },
      {
        name  = "NRFI_EVIDENCE_BUCKET"
        value = aws_s3_bucket.evidence.id
      },
      {
        name  = "NRFI_LOCKED_HOLDOUT_ACCESS"
        value = "DENIED"
      },
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.batch.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "baseline"
      }
    }
  })

  retry_strategy {
    attempts = 1
  }

  timeout {
    attempt_duration_seconds = 7200
  }
}
