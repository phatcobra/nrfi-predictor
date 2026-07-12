# Terraform configuration for NRFI/YRFI Prediction System on AWS
# This deploys the complete infrastructure including:
# - S3 buckets for data storage
# - Lambda functions for ingestion and prediction
# - API Gateway for REST API
# - EventBridge for scheduling
# - Secrets Manager for credentials
# - CloudWatch for monitoring

terraform {
  required_version = ">= 1.0"
  
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
  
  backend "s3" {
    bucket = "nrfi-predictor-terraform-state"
    key    = "nrfi-predictor/terraform.tfstate"
    region = "us-east-1"
    encrypt = true
  }
}

provider "aws" {
  region = var.aws_region
  
  default_tags {
    tags = {
      Project     = "NRFI-Predictor"
      Environment = var.environment
      ManagedBy   = "Terraform"
    }
  }
}

# Variables
variable "aws_region" {
  description = "AWS region to deploy resources"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string
  default     = "prod"
}

variable "project_name" {
  description = "Project name for resource naming"
  type        = string
  default     = "nrfi-predictor"
}

# S3 Buckets
resource "aws_s3_bucket" "data_raw" {
  bucket = "${var.project_name}-data-raw-${var.environment}"
}

resource "aws_s3_bucket" "data_processed" {
  bucket = "${var.project_name}-data-processed-${var.environment}"
}

resource "aws_s3_bucket" "models" {
  bucket = "${var.project_name}-models-${var.environment}"
}

resource "aws_s3_bucket" "predictions" {
  bucket = "${var.project_name}-predictions-${var.environment}"
}

resource "aws_s3_bucket_versioning" "models_versioning" {
  bucket = aws_s3_bucket.models.id
  
  versioning_configuration {
    status = "Enabled"
  }
}

# Secrets Manager for API keys and credentials
resource "aws_secretsmanager_secret" "sportsdata_api_key" {
  name = "${var.project_name}/sportsdata-api-key"
  description = "SportsDataIO API key"
}

resource "aws_secretsmanager_secret" "opticodds_api_key" {
  name = "${var.project_name}/opticodds-api-key"
  description = "OpticOdds API key"
}

resource "aws_secretsmanager_secret" "snowflake_credentials" {
  name = "${var.project_name}/snowflake-credentials"
  description = "Snowflake database credentials"
}

resource "aws_secretsmanager_secret" "sentry_dsn" {
  name = "${var.project_name}/sentry-dsn"
  description = "Sentry DSN for error monitoring"
}

resource "aws_secretsmanager_secret" "posthog_api_key" {
  name = "${var.project_name}/posthog-api-key"
  description = "PostHog API key for analytics"
}

# IAM Role for Lambda functions
resource "aws_iam_role" "lambda_execution_role" {
  name = "${var.project_name}-lambda-execution-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "lambda_policy" {
  name = "${var.project_name}-lambda-policy"
  role = aws_iam_role.lambda_execution_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:*:*:*"
      },
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:ListBucket"
        ]
        Resource = [
          "${aws_s3_bucket.data_raw.arn}/*",
          "${aws_s3_bucket.data_processed.arn}/*",
          "${aws_s3_bucket.models.arn}/*",
          "${aws_s3_bucket.predictions.arn}/*",
          aws_s3_bucket.data_raw.arn,
          aws_s3_bucket.data_processed.arn,
          aws_s3_bucket.models.arn,
          aws_s3_bucket.predictions.arn
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue"
        ]
        Resource = [
          aws_secretsmanager_secret.sportsdata_api_key.arn,
          aws_secretsmanager_secret.opticodds_api_key.arn,
          aws_secretsmanager_secret.snowflake_credentials.arn,
          aws_secretsmanager_secret.sentry_dsn.arn,
          aws_secretsmanager_secret.posthog_api_key.arn
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_basic_execution" {
  role       = aws_iam_role.lambda_execution_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Lambda Layer for Python dependencies
resource "aws_lambda_layer_version" "dependencies" {
  filename   = "lambda_layer.zip"  # Build this with: pip install -r requirements.txt -t python/
  layer_name = "${var.project_name}-dependencies"

  compatible_runtimes = ["python3.11"]
}

# Lambda function for daily data ingestion
resource "aws_lambda_function" "ingest_data" {
  filename      = "lambda_ingest.zip"
  function_name = "${var.project_name}-ingest-data"
  role          = aws_iam_role.lambda_execution_role.arn
  handler       = "ingest_handler.handler"

  runtime = "python3.11"
  timeout = 300
  memory_size = 1024

  layers = [aws_lambda_layer_version.dependencies.arn]

  environment {
    variables = {
      ENV                     = var.environment
      S3_RAW_BUCKET          = aws_s3_bucket.data_raw.id
      SPORTSDATA_SECRET_NAME = aws_secretsmanager_secret.sportsdata_api_key.name
      OPTICODDS_SECRET_NAME  = aws_secretsmanager_secret.opticodds_api_key.name
      SNOWFLAKE_SECRET_NAME  = aws_secretsmanager_secret.snowflake_credentials.name
      SENTRY_SECRET_NAME     = aws_secretsmanager_secret.sentry_dsn.name
    }
  }
}

# Lambda function for daily predictions
resource "aws_lambda_function" "predict_daily" {
  filename      = "lambda_predict.zip"
  function_name = "${var.project_name}-predict-daily"
  role          = aws_iam_role.lambda_execution_role.arn
  handler       = "predict_daily.handler"

  runtime = "python3.11"
  timeout = 600
  memory_size = 2048

  layers = [aws_lambda_layer_version.dependencies.arn]

  environment {
    variables = {
      ENV                     = var.environment
      S3_MODELS_BUCKET       = aws_s3_bucket.models.id
      S3_PREDICTIONS_BUCKET  = aws_s3_bucket.predictions.id
      SNOWFLAKE_SECRET_NAME  = aws_secretsmanager_secret.snowflake_credentials.name
      SENTRY_SECRET_NAME     = aws_secretsmanager_secret.sentry_dsn.name
      POSTHOG_SECRET_NAME    = aws_secretsmanager_secret.posthog_api_key.name
    }
  }
}

# Lambda function for API
resource "aws_lambda_function" "api" {
  filename      = "lambda_api.zip"
  function_name = "${var.project_name}-api"
  role          = aws_iam_role.lambda_execution_role.arn
  handler       = "api.handler"

  runtime = "python3.11"
  timeout = 30
  memory_size = 512

  layers = [aws_lambda_layer_version.dependencies.arn]

  environment {
    variables = {
      ENV                     = var.environment
      SNOWFLAKE_SECRET_NAME  = aws_secretsmanager_secret.snowflake_credentials.name
      SENTRY_SECRET_NAME     = aws_secretsmanager_secret.sentry_dsn.name
    }
  }
}

# API Gateway
resource "aws_apigatewayv2_api" "api" {
  name          = "${var.project_name}-api"
  protocol_type = "HTTP"
  
  cors_configuration {
    allow_origins = ["*"]
    allow_methods = ["GET", "POST", "OPTIONS"]
    allow_headers = ["*"]
  }
}

resource "aws_apigatewayv2_integration" "api_integration" {
  api_id = aws_apigatewayv2_api.api.id

  integration_uri    = aws_lambda_function.api.invoke_arn
  integration_type   = "AWS_PROXY"
  integration_method = "POST"
}

resource "aws_apigatewayv2_route" "api_route" {
  api_id = aws_apigatewayv2_api.api.id

  route_key = "$default"
  target    = "integrations/${aws_apigatewayv2_integration.api_integration.id}"
}

resource "aws_apigatewayv2_stage" "api_stage" {
  api_id = aws_apigatewayv2_api.api.id

  name        = var.environment
  auto_deploy = true

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api_logs.arn
    format = jsonencode({
      requestId      = "$context.requestId"
      ip             = "$context.identity.sourceIp"
      requestTime    = "$context.requestTime"
      httpMethod     = "$context.httpMethod"
      routeKey       = "$context.routeKey"
      status         = "$context.status"
      protocol       = "$context.protocol"
      responseLength = "$context.responseLength"
    })
  }
}

resource "aws_lambda_permission" "api_gateway" {
  statement_id  = "AllowExecutionFromAPIGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api.function_name
  principal     = "apigateway.amazonaws.com"

  source_arn = "${aws_apigatewayv2_api.api.execution_arn}/*/*"
}

# CloudWatch Log Groups
resource "aws_cloudwatch_log_group" "api_logs" {
  name              = "/aws/apigateway/${var.project_name}-api"
  retention_in_days = 30
}

resource "aws_cloudwatch_log_group" "ingest_logs" {
  name              = "/aws/lambda/${aws_lambda_function.ingest_data.function_name}"
  retention_in_days = 30
}

resource "aws_cloudwatch_log_group" "predict_logs" {
  name              = "/aws/lambda/${aws_lambda_function.predict_daily.function_name}"
  retention_in_days = 30
}

# EventBridge Rules for scheduling
resource "aws_cloudwatch_event_rule" "daily_ingestion" {
  name                = "${var.project_name}-daily-ingestion"
  description         = "Trigger daily data ingestion"
  schedule_expression = "cron(0 10 * * ? *)"  # 10:00 AM UTC daily
}

resource "aws_cloudwatch_event_target" "daily_ingestion" {
  rule      = aws_cloudwatch_event_rule.daily_ingestion.name
  target_id = "IngestLambda"
  arn       = aws_lambda_function.ingest_data.arn
}

resource "aws_lambda_permission" "allow_eventbridge_ingestion" {
  statement_id  = "AllowExecutionFromEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ingest_data.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.daily_ingestion.arn
}

resource "aws_cloudwatch_event_rule" "daily_predictions" {
  name                = "${var.project_name}-daily-predictions"
  description         = "Trigger daily predictions"
  schedule_expression = "cron(0 12 * * ? *)"  # 12:00 PM UTC daily
}

resource "aws_cloudwatch_event_target" "daily_predictions" {
  rule      = aws_cloudwatch_event_rule.daily_predictions.name
  target_id = "PredictLambda"
  arn       = aws_lambda_function.predict_daily.arn
}

resource "aws_lambda_permission" "allow_eventbridge_predictions" {
  statement_id  = "AllowExecutionFromEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.predict_daily.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.daily_predictions.arn
}

# Outputs
output "api_endpoint" {
  description = "API Gateway endpoint URL"
  value       = "${aws_apigatewayv2_api.api.api_endpoint}/${var.environment}"
}

output "s3_buckets" {
  description = "S3 bucket names"
  value = {
    raw        = aws_s3_bucket.data_raw.id
    processed  = aws_s3_bucket.data_processed.id
    models     = aws_s3_bucket.models.id
    predictions = aws_s3_bucket.predictions.id
  }
}

output "lambda_functions" {
  description = "Lambda function names"
  value = {
    ingest  = aws_lambda_function.ingest_data.function_name
    predict = aws_lambda_function.predict_daily.function_name
    api     = aws_lambda_function.api.function_name
  }
}
