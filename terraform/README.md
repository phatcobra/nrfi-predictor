# AWS baseline foundation

This directory defines the cost-conscious historical foundation for reproducing
the frozen 2022-2024 NRFI/YRFI baseline in AWS. It is probability-only
infrastructure. It does not create market, odds, wagering, bankroll, or betting
resources.

## Safety state

The configuration has not been applied. AWS authentication, account inventory,
network reuse, region approval, monthly budget, notification email, and access
mode must be verified before a plan can authorize deployment.

The S3 backend is intentionally partial. Supply its bucket, key, region,
encryption, and lock-table settings at `terraform init` time from an approved
bootstrap process. Never commit backend account details or a `.tfvars` file.

`enable_batch` and `enable_budget` default to `false`. Enabling Batch requires
explicitly approved existing private subnets and security groups. Enabling the
budget requires a positive approved monthly limit and a valid notification
email.

## Implemented boundary

- KMS keys with rotation for platform data and the separately protected holdout.
- S3 buckets with versioning, KMS encryption, TLS-only policies, ownership
  enforcement, public-access blocking, lifecycle controls, and Object Lock for
  immutable raw data and evidence.
- A separate locked-holdout bucket and KMS key. Batch and SageMaker training
  roles have explicit deny policies and receive no ordinary holdout grants.
- An immutable, KMS-encrypted ECR repository with scan-on-push.
- Optional AWS Batch on Fargate with a bounded vCPU ceiling and no public IP.
- Least-privilege Batch job access to admitted raw, lake, model, prediction, and
  evidence locations only.
- Glue Data Catalog and a scan-capped, KMS-encrypted Athena workgroup.
- A SageMaker training role and candidate Model Package Group. Registration is
  not approval and does not create an endpoint.
- An optional tagged monthly AWS Budget with 50% forecast, 80% actual, and 100%
  actual notifications.

No data, container, model, endpoint, API, browser application, or holdout object
is created or uploaded by this configuration.

## Storage key contract

Only inventory-approved assets may be transferred. Use immutable snapshot IDs
and Parquet for analytical datasets.

| Bucket | Approved key families |
| --- | --- |
| raw | `admitted/<source>/<snapshot>/...` |
| lake | `normalized/`, `features/`, `models/`, `calibrators/`, `predictions/`, `manifests/`, `checksums/`, `rejected/`, `athena-results/` |
| evidence | `evaluation/`, `replay/`, `prediction-audit/`, `release/` |
| logs | operational logs that are not immutable evidence |
| locked holdout | protected 2025 evidence only; unavailable to training and ordinary inference roles |

## Local validation

Run from this directory after installing an approved Terraform version:

```text
terraform fmt -check -recursive
terraform init -backend=false
terraform validate
```

Validation must not use AWS credentials and must not contact the AWS API beyond
downloading the pinned provider during initialization. Do not run `plan` or
`apply` until the AWS read-only preflight and all four cost/access decisions are
recorded.

## Required deployment inputs

Before the first plan, record and review:

1. approved AWS region;
2. maximum monthly AWS budget;
3. budget notification email;
4. private or public application access;
5. verified existing VPC, private subnets, security groups, CloudTrail, budgets,
   billing alarms, quotas, and GitHub OIDC state;
6. immutable Git commit and container digest;
7. manifest-approved data snapshot and the explicit exclusion of the locked
   2025 holdout.

The first remote milestone is analytical equivalence with the preserved local
baseline. Any discrepancy must be investigated rather than accepted.
