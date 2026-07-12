#!/bin/bash
# NRFI Predictor - AWS Deployment Script
# This script automates the complete deployment of the NRFI prediction system

set -e  # Exit on error

PROJECT_NAME="nrfi-predictor"
ENVIRONMENT="${1:-prod}"
AWS_REGION="${2:-us-east-1}"

echo "===================================="
echo "NRFI Predictor Deployment Script"
echo "Environment: $ENVIRONMENT"
echo "Region: $AWS_REGION"
echo "===================================="

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored output
print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

print_info() {
    echo -e "${YELLOW}➜ $1${NC}"
}

# Check prerequisites
print_info "Checking prerequisites..."

if ! command -v aws &> /dev/null; then
    print_error "AWS CLI not found. Please install: https://aws.amazon.com/cli/"
    exit 1
fi

if ! command -v terraform &> /dev/null; then
    print_error "Terraform not found. Please install: https://www.terraform.io/downloads"
    exit 1
fi

if ! command -v python3 &> /dev/null; then
    print_error "Python 3 not found. Please install Python 3.11+"
    exit 1
fi

print_success "All prerequisites installed"

# Step 1: Create Terraform state bucket
print_info "Step 1: Creating Terraform state bucket..."
STATE_BUCKET="${PROJECT_NAME}-terraform-state"

if aws s3 ls "s3://${STATE_BUCKET}" 2>&1 | grep -q 'NoSuchBucket'; then
    aws s3 mb "s3://${STATE_BUCKET}" --region "$AWS_REGION"
    aws s3api put-bucket-versioning \
        --bucket "$STATE_BUCKET" \
        --versioning-configuration Status=Enabled
    print_success "Created Terraform state bucket: $STATE_BUCKET"
else
    print_success "Terraform state bucket already exists: $STATE_BUCKET"
fi

# Step 2: Set up secrets in AWS Secrets Manager
print_info "Step 2: Setting up AWS Secrets Manager..."

echo ""
echo "Please provide the following API keys and credentials:"
echo "(Press Enter to skip if already configured)"
echo ""

# Function to create or update secret
create_or_update_secret() {
    local secret_name=$1
    local secret_description=$2
    local prompt_message=$3
    
    if aws secretsmanager describe-secret --secret-id "$secret_name" --region "$AWS_REGION" &>/dev/null; then
        print_info "Secret $secret_name already exists. Skip updating? (y/n)"
        read -r skip_update
        if [[ $skip_update == "y" ]]; then
            return
        fi
    fi
    
    echo -n "$prompt_message: "
    read -rs secret_value
    echo ""
    
    if [ -n "$secret_value" ]; then
        aws secretsmanager create-secret \
            --name "$secret_name" \
            --description "$secret_description" \
            --secret-string "$secret_value" \
            --region "$AWS_REGION" 2>/dev/null || \
        aws secretsmanager update-secret \
            --secret-id "$secret_name" \
            --secret-string "$secret_value" \
            --region "$AWS_REGION"
        print_success "Configured secret: $secret_name"
    else
        print_info "Skipped: $secret_name"
    fi
}

create_or_update_secret \
    "${PROJECT_NAME}/sportsdata-api-key" \
    "SportsDataIO API key" \
    "Enter SportsDataIO API key"

create_or_update_secret \
    "${PROJECT_NAME}/opticodds-api-key" \
    "OpticOdds API key" \
    "Enter OpticOdds API key"

# For Snowflake, store as JSON
print_info "Snowflake credentials (JSON format required)"
echo -n "Enter Snowflake account: "
read -r sf_account
echo -n "Enter Snowflake user: "
read -r sf_user
echo -n "Enter Snowflake password: "
read -rs sf_password
echo ""
echo -n "Enter Snowflake warehouse: "
read -r sf_warehouse
echo -n "Enter Snowflake database: "
read -r sf_database

if [ -n "$sf_account" ]; then
    SF_CREDS=$(cat <<EOF
{
  "account": "$sf_account",
  "user": "$sf_user",
  "password": "$sf_password",
  "warehouse": "$sf_warehouse",
  "database": "$sf_database"
}
EOF
)
    
    aws secretsmanager create-secret \
        --name "${PROJECT_NAME}/snowflake-credentials" \
        --description "Snowflake database credentials" \
        --secret-string "$SF_CREDS" \
        --region "$AWS_REGION" 2>/dev/null || \
    aws secretsmanager update-secret \
        --secret-id "${PROJECT_NAME}/snowflake-credentials" \
        --secret-string "$SF_CREDS" \
        --region "$AWS_REGION"
    print_success "Configured Snowflake credentials"
fi

create_or_update_secret \
    "${PROJECT_NAME}/sentry-dsn" \
    "Sentry DSN for error monitoring" \
    "Enter Sentry DSN"

create_or_update_secret \
    "${PROJECT_NAME}/posthog-api-key" \
    "PostHog API key for analytics" \
    "Enter PostHog API key"

# Step 3: Build Lambda packages
print_info "Step 3: Building Lambda deployment packages..."

mkdir -p build/lambda

# Build dependencies layer
print_info "Building Python dependencies layer..."
mkdir -p build/lambda/python
pip install -r requirements.txt -t build/lambda/python/ --quiet
cd build/lambda
zip -r ../../lambda_layer.zip python/ -q
cd ../..
print_success "Built lambda_layer.zip"

# Build Lambda functions
print_info "Building Lambda function packages..."

# Ingest Lambda
cp -r src/* build/lambda/
cd build/lambda
zip -r ../../lambda_ingest.zip ingest_*.py snowflake_loader.py config.py -q
cd ../..
print_success "Built lambda_ingest.zip"

# Predict Lambda
cd build/lambda
zip -r ../../lambda_predict.zip predict_daily.py features.py train.py snowflake_loader.py config.py ingest_*.py -q
cd ../..
print_success "Built lambda_predict.zip"

# API Lambda
cd build/lambda
zip -r ../../lambda_api.zip api.py snowflake_loader.py predict_daily.py features.py train.py config.py -q
cd ../..
print_success "Built lambda_api.zip"

rm -rf build/

# Step 4: Initialize and apply Terraform
print_info "Step 4: Deploying infrastructure with Terraform..."

cd terraform

terraform init \
    -backend-config="bucket=$STATE_BUCKET" \
    -backend-config="region=$AWS_REGION"

terraform plan \
    -var="environment=$ENVIRONMENT" \
    -var="aws_region=$AWS_REGION" \
    -out=tfplan

echo ""
print_info "Review the Terraform plan above. Continue with deployment? (yes/no)"
read -r continue_deploy

if [[ $continue_deploy == "yes" ]]; then
    terraform apply tfplan
    print_success "Infrastructure deployed successfully!"
    
    # Save outputs
    terraform output -json > ../deployment_outputs.json
    
    API_ENDPOINT=$(terraform output -raw api_endpoint)
    print_success "API Endpoint: $API_ENDPOINT"
else
    print_info "Deployment cancelled."
    exit 0
fi

cd ..

# Step 5: Initialize Snowflake schema
print_info "Step 5: Initializing Snowflake database schema..."
print_info "Run: python scripts/init_snowflake.py"
echo "(Execute this manually after deployment)"

# Step 6: Upload initial model (if exists)
if [ -f "models/nrfi_model_latest.txt" ]; then
    print_info "Step 6: Uploading initial model to S3..."
    MODEL_BUCKET=$(cat deployment_outputs.json | python3 -c "import sys, json; print(json.load(sys.stdin)['s3_buckets']['value']['models'])")
    aws s3 cp models/ "s3://$MODEL_BUCKET/" --recursive
    print_success "Model uploaded to S3"
else
    print_info "Step 6: No pre-trained model found. Run training after data backfill."
fi

echo ""
echo "===================================="
print_success "Deployment Complete!"
echo "===================================="
echo ""
echo "Next steps:"
echo "1. Initialize Snowflake: python scripts/init_snowflake.py"
echo "2. Backfill historical data: python scripts/backfill_data.py --start-date 2023-01-01"
echo "3. Train initial model: python src/train.py"
echo "4. Test API: curl $API_ENDPOINT/health"
echo ""
echo "Daily automation is now active:"
echo "  - Data ingestion: 10:00 AM UTC daily"
echo "  - Predictions: 12:00 PM UTC daily"
echo ""
print_success "System is ready!"
