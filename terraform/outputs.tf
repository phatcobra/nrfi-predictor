output "storage" {
  description = "Non-secret storage identities for admitted data and evidence."
  value = {
    raw      = aws_s3_bucket.raw.id
    lake     = aws_s3_bucket.lake.id
    evidence = aws_s3_bucket.evidence.id
  }
}

output "pipeline_repository_url" {
  description = "ECR repository for the deterministic pipeline container."
  value       = aws_ecr_repository.pipeline.repository_url
}

output "batch" {
  description = "Batch resources when explicitly enabled after network approval."
  value = var.enable_batch ? {
    compute_environment = aws_batch_compute_environment.baseline[0].arn
    job_queue           = aws_batch_job_queue.baseline[0].arn
    job_definition      = aws_batch_job_definition.baseline[0].arn
  } : null
}

output "locked_holdout_training_access" {
  description = "Fail-closed invariant for training and ordinary batch roles."
  value       = "NOT_PROVISIONED_AND_DENIED"
}

output "private_network_monthly_floor_usd" {
  description = "Approximate 730-hour floor for three interface endpoints at the verified us-east-2 price; excludes data processing."
  value       = 21.90
}
