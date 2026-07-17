output "storage" {
  description = "Non-secret storage identities for admitted data and evidence."
  value = {
    raw      = aws_s3_bucket.raw.id
    lake     = aws_s3_bucket.lake.id
    evidence = aws_s3_bucket.evidence.id
    logs     = aws_s3_bucket.logs.id
    holdout  = aws_s3_bucket.holdout.id
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

output "analytics" {
  description = "Historical catalog and query workgroup."
  value = {
    glue_database    = aws_glue_catalog_database.historical.name
    athena_workgroup = aws_athena_workgroup.historical.name
    model_group      = aws_sagemaker_model_package_group.candidates.model_package_group_name
  }
}

output "locked_holdout_training_access" {
  description = "Fail-closed invariant for training and ordinary batch roles."
  value       = "DENIED"
}
