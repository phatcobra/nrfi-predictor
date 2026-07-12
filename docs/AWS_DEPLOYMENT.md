# AWS Deployment Architecture

## Complete NRFI Prediction System on AWS

This document shows how to deploy the entire **autonomous NRFI/YRFI prediction system** on AWS with full automation, scalability, and monitoring.

---

## Architecture Overview

```
┌────────────────────────────────────────────────────────────────────┐
│  DATA INGESTION (Scheduled via EventBridge)                       │
│  ├─ Lambda: ingest_opticodds (daily, hourly for live odds)       │
│  ├─ Lambda: ingest_sportsdata (daily game data)                  │
│  └─ Lambda: ingest_statcast (weekly historical backfill)         │
└─────────────────┬──────────────────────────────────────────────────┘
                  │
                  ▼
┌────────────────────────────────────────────────────────────────────┐
│  DATA STORAGE                                                      │
│  ├─ S3: Raw data lake (Parquet, partitioned by date)             │
│  ├─ Snowflake: Analytics warehouse (NRFI system via AWS PrivateLink)│
│  └─ DynamoDB: Low-latency lookups (latest odds, lineups)         │
└─────────────────┬──────────────────────────────────────────────────┘
                  │
                  ▼
┌────────────────────────────────────────────────────────────────────┐
│  FEATURE ENGINEERING & ML                                          │
│  ├─ SageMaker Processing: Batch feature computation               │
│  ├─ SageMaker Training: Weekly model retraining (LightGBM)       │
│  └─ SageMaker Endpoints: Real-time inference                     │
└─────────────────┬──────────────────────────────────────────────────┘
                  │
                  ▼
┌────────────────────────────────────────────────────────────────────┐
│  DAILY PREDICTION PIPELINE (Step Functions orchestration)         │
│  1. Fetch today's games (OpticOdds + SportsDataIO)               │
│  2. Compute features (SageMaker Processing)                       │
│  3. Generate predictions (SageMaker Endpoint)                     │
│  4. Store predictions (Snowflake + S3)                            │
│  5. Detect +EV opportunities (Lambda + PostHog tracking)          │
└─────────────────┬──────────────────────────────────────────────────┘
                  │
       ┌──────────┴──────────┐
       ▼                     ▼
┌─────────────────┐   ┌────────────────────┐
│  API GATEWAY    │   │  DASHBOARD         │
│  + Lambda       │   │  (Amplify Hosting) │
│  (REST API)     │   │  Streamlit App     │
└─────────────────┘   └────────────────────┘
```

---

## AWS Services Used

### Compute
- **Lambda**: Serverless ingestion, API endpoints, orchestration
- **SageMaker**: ML training, inference, feature engineering
- **ECS Fargate** (optional): Long-running dashboard/API if needed

### Storage
- **S3**: Data lake (raw data, model artifacts, predictions)
- **DynamoDB**: Fast k/v lookups (latest odds, player stats cache)
- **Snowflake** (via AWS PrivateLink): Analytics warehouse

### Orchestration & Scheduling
- **EventBridge**: Cron triggers (daily/hourly ingestion, weekly retrain)
- **Step Functions**: Complex pipeline orchestration (prediction workflow)

### Monitoring & Observability
- **CloudWatch**: Logs, metrics, alarms
- **Sentry** (SaaS): Python error tracking
- **PostHog** (SaaS): Analytics, A/B testing
- **X-Ray**: Distributed tracing

### Networking
- **VPC**: Isolated network for SageMaker, RDS (if using Postgres)
- **PrivateLink**: Secure Snowflake connection
- **API Gateway**: RESTful API for predictions

---

## Deployment Steps

### 1. Set Up AWS Account

```bash
# Install AWS CLI
aws configure
# Enter: Access Key, Secret Key, Region (us-east-1), Format (json)

# Install Terraform (infrastructure as code)
brew install terraform  # macOS
# or: apt-get install terraform  # Linux
```

### 2. Create S3 Buckets

```bash
# Data lake
aws s3 mb s3://nrfi-data-lake-ACCOUNT_ID

# Model artifacts
aws s3 mb s3://nrfi-models-ACCOUNT_ID

# Predictions
aws s3 mb s3://nrfi-predictions-ACCOUNT_ID
```

### 3. Set Up Snowflake on AWS

**Option A: Snowflake on AWS (recommended)**

1. Sign up for Snowflake: https://signup.snowflake.com
2. Choose AWS region matching your deployment (us-east-1)
3. Create storage integration for S3 access:

```sql
-- In Snowflake worksheet
CREATE STORAGE INTEGRATION nrfi_s3_integration
  TYPE = EXTERNAL_STAGE
  STORAGE_PROVIDER = 'S3'
  ENABLED = TRUE
  STORAGE_AWS_ROLE_ARN = 'arn:aws:iam::YOUR_ACCOUNT:role/SnowflakeS3Role'
  STORAGE_ALLOWED_LOCATIONS = ('s3://nrfi-data-lake-ACCOUNT_ID/');

-- Grant permissions
GRANT USAGE ON INTEGRATION nrfi_s3_integration TO ROLE ACCOUNTADMIN;
```

4. Set up AWS PrivateLink (secure connection):
```bash
# Get Snowflake PrivateLink endpoint from Snowflake console
# Create VPC Endpoint in AWS:
aws ec2 create-vpc-endpoint \
  --vpc-id vpc-xxxxx \
  --service-name com.amazonaws.vpce.us-east-1.vpce-svc-SNOWFLAKE_ID \
  --vpc-endpoint-type Interface
```

### 4. Deploy Lambda Functions

**Package dependencies:**

```bash
# Create deployment package
cd src/
pip install -r ../requirements.txt -t ./package
cp ingest_opticodds.py package/
cd package && zip -r ../ingest_opticodds.zip . && cd ..

# Upload to S3
aws s3 cp ingest_opticodds.zip s3://nrfi-models-ACCOUNT_ID/lambdas/
```

**Create Lambda (Terraform example):**

```hcl
# terraform/lambda.tf
resource "aws_lambda_function" "ingest_opticodds" {
  function_name = "nrfi-ingest-opticodds"
  s3_bucket     = "nrfi-models-${data.aws_caller_identity.current.account_id}"
  s3_key        = "lambdas/ingest_opticodds.zip"
  handler       = "ingest_opticodds.lambda_handler"
  runtime       = "python3.11"
  timeout       = 900  # 15 min
  memory_size   = 1024
  
  environment {
    variables = {
      OPTIC_API_KEY       = var.optic_api_key
      SNOWFLAKE_ACCOUNT   = var.snowflake_account
      SNOWFLAKE_USER      = var.snowflake_user
      SNOWFLAKE_PASSWORD  = var.snowflake_password
      SENTRY_DSN          = var.sentry_dsn
      POSTHOG_API_KEY     = var.posthog_api_key
    }
  }
  
  role = aws_iam_role.lambda_exec.arn
}
```

###5. Set Up EventBridge Schedules

```hcl
# terraform/eventbridge.tf
resource "aws_cloudwatch_event_rule" "daily_ingestion" {
  name                = "nrfi-daily-ingestion"
  description         = "Trigger daily NRFI data ingestion"
  schedule_expression = "cron(0 14 * * ? *)"  # 10 AM ET = 14:00 UTC
}

resource "aws_cloudwatch_event_target" "lambda_ingest" {
  rule      = aws_cloudwatch_event_rule.daily_ingestion.name
  target_id = "IngestOpticOdds"
  arn       = aws_lambda_function.ingest_opticodds.arn
}

resource "aws_lambda_permission" "allow_eventbridge" {
  statement_id  = "AllowExecutionFromEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ingest_opticodds.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.daily_ingestion.arn
}
```

### 6. Deploy SageMaker Model

**Train model:**

```python
# train_on_sagemaker.py
import sagemaker
from sagemaker.sklearn import SKLearn

sess = sagemaker.Session()
role = 'arn:aws:iam::ACCOUNT:role/SageMakerRole'

sklearn_estimator = SKLearn(
    entry_point='src/train.py',
    role=role,
    instance_type='ml.m5.2xlarge',
    framework_version='1.2-1',
    py_version='py3',
    hyperparameters={
        'model_type': 'lightgbm',
        'calibration': 'isotonic',
    }
)

sklearn_estimator.fit({'train': 's3://nrfi-data-lake/training_data/'})
```

**Deploy endpoint:**

```python
predictor = sklearn_estimator.deploy(
    initial_instance_count=1,
    instance_type='ml.t2.medium',
    endpoint_name='nrfi-predictor-v1'
)
```

### 7. API Gateway + Lambda

```hcl
# terraform/api_gateway.tf
resource "aws_api_gateway_rest_api" "nrfi_api" {
  name        = "nrfi-api"
  description = "NRFI/YRFI Prediction API"
}

resource "aws_api_gateway_resource" "predictions" {
  rest_api_id = aws_api_gateway_rest_api.nrfi_api.id
  parent_id   = aws_api_gateway_rest_api.nrfi_api.root_resource_id
  path_part   = "predictions"
}

resource "aws_api_gateway_method" "get_predictions" {
  rest_api_id   = aws_api_gateway_rest_api.nrfi_api.id
  resource_id   = aws_api_gateway_resource.predictions.id
  http_method   = "GET"
  authorization = "API_KEY"
}
```

### 8. Deploy Dashboard (AWS Amplify)

```bash
# Build Streamlit dashboard as static site
streamlit run src/dashboard.py

# Or deploy via Amplify:
aws amplify create-app --name nrfi-dashboard \
  --repository https://github.com/phatcobra/nrfi-predictor \
  --oauth-token GITHUB_TOKEN

aws amplify create-branch --app-id APP_ID --branch-name main
aws amplify start-deployment --app-id APP_ID --branch-name main
```

---

## Environment Variables (AWS Secrets Manager)

```bash
# Store secrets
aws secretsmanager create-secret --name nrfi/optic-api-key \
  --secret-string "YOUR_OPTIC_API_KEY"

aws secretsmanager create-secret --name nrfi/snowflake-creds \
  --secret-string '{"user":"SNOW_USER","password":"SNOW_PASS","account":"SNOW_ACCOUNT"}'

aws secretsmanager create-secret --name nrfi/sentry-dsn \
  --secret-string "https://xxxxx@sentry.io/123456"
```

**Lambda fetches from Secrets Manager:**

```python
# In Lambda handler
import boto3
import json

def get_secret(secret_name):
    client = boto3.client('secretsmanager')
    response = client.get_secret_value(SecretId=secret_name)
    return json.loads(response['SecretString'])

OPTIC_API_KEY = get_secret('nrfi/optic-api-key')
```

---

## Cost Estimation (Monthly)

| Service | Usage | Cost |
|---------|-------|------|
| **Lambda** | 50 invocations/day × 5 min avg | ~$10 |
| **SageMaker Endpoint** | ml.t2.medium × 730 hrs | ~$35 |
| **S3** | 100 GB storage + requests | ~$3 |
| **EventBridge** | 100 rules | Free |
| **API Gateway** | 10K requests/month | ~$0.04 |
| **Snowflake** | XS warehouse × 10 hrs/week | ~$50 |
| **Sentry** (SaaS) | Free tier | $0 |
| **PostHog** (SaaS) | Free tier | $0 |
| **OpticOdds** | Starter plan | ~$99 |
| **SportsDataIO** | After trial (~$50/mo or use free MLB API) | $50 |
| **Total** | | **~$247/month** |

---

## Scaling & Optimization

### High-Volume Optimization

If ingesting odds every minute during live games:

1. **Switch to Kinesis Data Streams**:
   ```bash
   aws kinesis create-stream --stream-name nrfi-odds-stream --shard-count 1
   ```

2. **Use Lambda + Kinesis**:
   - OpticOdds → Kinesis → Lambda → Snowflake (batched inserts)

3. **Enable Snowflake Unistore** for real-time analytics

### Cost Optimization

- Use **Lambda ARM (Graviton2)** for 20% cost savings
- **S3 Intelligent-Tiering** for old data
- **SageMaker Spot Instances** for training (70% savings)
- **Reserved Capacity** for Snowflake if predictable usage

---

## Monitoring & Alerts

```hcl
# terraform/cloudwatch.tf
resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  alarm_name          = "nrfi-lambda-errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Sum"
  threshold           = 5
  alarm_actions       = [aws_sns_topic.alerts.arn]
  
  dimensions = {
    FunctionName = aws_lambda_function.ingest_opticodds.function_name
  }
}

resource "aws_sns_topic" "alerts" {
  name = "nrfi-alerts"
}

resource "aws_sns_topic_subscription" "alerts_email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = "your-email@example.com"
}
```

---

## Complete Terraform Deployment

```bash
# Clone repo
git clone https://github.com/phatcobra/nrfi-predictor.git
cd nrfi-predictor/terraform

# Initialize
terraform init

# Plan
terraform plan \
  -var="optic_api_key=YOUR_KEY" \
  -var="snowflake_account=YOUR_ACCOUNT"

# Apply
terraform apply

# Outputs:
# - API Gateway URL
# - SageMaker Endpoint Name
# - S3 Bucket Names
# - Lambda Function ARNs
```

---

## Next Steps

1. **Deploy infrastructure**: `terraform apply`
2. **Backfill historical data**: Run Lambda manually for 2024 season
3. **Train initial model**: SageMaker training job
4. **Test API**: `curl https://API_ID.execute-api.us-east-1.amazonaws.com/predictions/today`
5. **Monitor**: CloudWatch + Sentry dashboards
6. **Iterate**: PostHog A/B tests for model improvements

---

**You now have an enterprise-grade, fully autonomous NRFI prediction system on AWS!**
