# AWS baseline foundation

This directory defines the minimum cost-bounded historical foundation for
reproducing the frozen 2022-2024 NRFI/YRFI baseline in AWS. It is
probability-only infrastructure. It does not create market, odds, wagering,
bankroll, or betting resources.

## Safety state

The configuration has not been applied. The approved deployment decisions are
`us-east-2`, an account-wide `$30` monthly budget, the separately supplied
sensitive notification address, and private networking. The account inventory
found no reusable private subnet, customer-managed KMS key, ECR repository,
Batch environment, budget, billing alarm, CloudTrail trail, or GitHub OIDC
provider. The existing S3 bucket and Athena workgroup do not meet the required
controls and are not reused.

The S3 backend is intentionally partial. Supply its bucket, key, region,
encryption, and lock-table settings at `terraform init` time from an approved
bootstrap process. Never commit backend account details or a `.tfvars` file.

`enable_batch` and `enable_budget` default to `false`. The first reviewed plan
must enable both and supply the approved sensitive notification address without
committing it. The private subnet CIDR and availability zone are explicit inputs
whose defaults match the verified non-overlapping `us-east-2` account layout.

## Implemented boundary

- One KMS key with rotation for admitted baseline data and evidence.
- S3 buckets with versioning, KMS encryption, TLS-only policies, ownership
  enforcement, public-access blocking, lifecycle controls, and Object Lock for
  immutable raw data and evidence.
- No holdout bucket or object. The locked 2025 holdout remains local, untouched,
  and explicitly denied by the Batch job role.
- An immutable, KMS-encrypted ECR repository with scan-on-push.
- A single-AZ private subnet with no internet route, a free S3 gateway endpoint,
  and exactly three paid interface endpoints: ECR API, ECR Docker, and
  CloudWatch Logs. The verified interface-endpoint rate is `$0.01` per endpoint
  hour, producing an approximate 730-hour floor of `$21.90` plus data processing.
- Optional AWS Batch on Fargate with a two-vCPU default ceiling, no public IP,
  one attempt, and a two-hour job timeout.
- Least-privilege Batch job access to admitted raw, lake, model, prediction, and
  evidence locations only.
- An optional account-wide monthly AWS Budget with 50% forecast, 80% actual,
  and 100% actual notifications.

Glue, Athena, SageMaker, online inference, and a separately protected holdout
bucket remain deferred until the preserved baseline is reproduced. This keeps
the first deployment below the approved ceiling and prevents infrastructure
expansion from replacing product evidence.

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

Operational logs remain in the bounded CloudWatch log group. No locked-holdout
storage is provisioned during the baseline replay.

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
5. verified existing VPC, subnets, security groups, CloudTrail, budgets, billing
   alarms, quotas, and GitHub OIDC state;
6. immutable Git commit and container digest;
7. manifest-approved data snapshot and the explicit exclusion of the locked
   2025 holdout.

The first remote milestone is analytical equivalence with the preserved local
baseline. Any discrepancy must be investigated rather than accepted.
