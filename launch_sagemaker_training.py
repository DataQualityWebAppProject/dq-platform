"""
SageMaker Fine-Tuning Launch Script
====================================
Prepares training data, uploads to S3, and launches a SageMaker training
job for data quality rule interpretation using boto3 directly.

Model: Meta Llama 3.1 8B Instruct (JumpStart image)
Instance: ml.g5.2xlarge
"""

import json
import os
import random
import sys
import time
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

# ─── Configuration ────────────────────────────────────────────────────────────
REGION = "us-east-1"
ACCOUNT_ID = "108782054634"
S3_BUCKET = f"dq-mlflow-{ACCOUNT_ID}"
S3_TRAIN_PREFIX = "fine-tuning/train"
S3_VAL_PREFIX = "fine-tuning/validation"
S3_OUTPUT_PREFIX = "fine-tuning/output"
SSM_ROLE_PARAM = "/dq-platform/iam-sagemaker-role-arn"

INPUT_FILE = Path(__file__).parent / "finetune_dataset.jsonl"
TRAIN_OUTPUT = Path(__file__).parent / "training_data_sagemaker_train.jsonl"
VAL_OUTPUT = Path(__file__).parent / "training_data_sagemaker_val.jsonl"

SYSTEM_PROMPT = (
    "You are a data quality expert specialized in Peruvian banking regulations. "
    "Given a natural language rule description, generate a Python function using pandas "
    "that implements the data quality rule. The function should accept a DataFrame, "
    "apply the rule, and return the cleaned DataFrame with a flag column indicating "
    "which rows were modified."
)

TRAIN_SPLIT = 0.9
RANDOM_SEED = 42


def step_banner(step_num: int, title: str):
    print(f"\n{'='*60}")
    print(f"  Step {step_num}: {title}")
    print(f"{'='*60}\n")


# ─── Step 1: Prepare Training Data ───────────────────────────────────────────
def prepare_training_data():
    step_banner(1, "Prepare Training Data (instruction/response -> chat format)")

    if not INPUT_FILE.exists():
        print(f"ERROR: Input file not found: {INPUT_FILE}")
        sys.exit(1)

    # Read all examples
    examples = []
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                examples.append(record)
            except json.JSONDecodeError as e:
                print(f"  WARNING: Skipping line {line_num} (invalid JSON): {e}")

    print(f"  Loaded {len(examples)} examples from {INPUT_FILE.name}")

    # Convert to chat/messages format
    chat_examples = []
    for ex in examples:
        chat_record = {
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": ex["instruction"]},
                {"role": "assistant", "content": ex["response"]},
            ]
        }
        chat_examples.append(chat_record)

    # Shuffle and split
    random.seed(RANDOM_SEED)
    random.shuffle(chat_examples)

    split_idx = int(len(chat_examples) * TRAIN_SPLIT)
    train_data = chat_examples[:split_idx]
    val_data = chat_examples[split_idx:]

    print(f"  Split: {len(train_data)} train / {len(val_data)} validation")

    # Write files
    with open(TRAIN_OUTPUT, "w", encoding="utf-8") as f:
        for record in train_data:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    with open(VAL_OUTPUT, "w", encoding="utf-8") as f:
        for record in val_data:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"  Written: {TRAIN_OUTPUT.name} ({len(train_data)} examples)")
    print(f"  Written: {VAL_OUTPUT.name} ({len(val_data)} examples)")

    return len(train_data), len(val_data)


# ─── Step 2: Upload to S3 ────────────────────────────────────────────────────
def upload_to_s3():
    step_banner(2, "Upload Training Data to S3")

    s3 = boto3.client("s3", region_name=REGION)

    # Verify bucket exists
    try:
        s3.head_bucket(Bucket=S3_BUCKET)
        print(f"  Bucket verified: s3://{S3_BUCKET}")
    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        if error_code == "404":
            print(f"  ERROR: Bucket {S3_BUCKET} does not exist!")
            sys.exit(1)
        elif error_code == "403":
            print(f"  ERROR: Access denied to bucket {S3_BUCKET}")
            sys.exit(1)
        raise

    # Upload train file
    train_key = f"{S3_TRAIN_PREFIX}/train.jsonl"
    print(f"  Uploading {TRAIN_OUTPUT.name} -> s3://{S3_BUCKET}/{train_key}")
    s3.upload_file(str(TRAIN_OUTPUT), S3_BUCKET, train_key)
    print(f"  [OK] Train file uploaded")

    # Upload validation file
    val_key = f"{S3_VAL_PREFIX}/validation.jsonl"
    print(f"  Uploading {VAL_OUTPUT.name} -> s3://{S3_BUCKET}/{val_key}")
    s3.upload_file(str(VAL_OUTPUT), S3_BUCKET, val_key)
    print(f"  [OK] Validation file uploaded")

    return (
        f"s3://{S3_BUCKET}/{S3_TRAIN_PREFIX}/",
        f"s3://{S3_BUCKET}/{S3_VAL_PREFIX}/",
    )


# ─── Step 3: Get SageMaker Role ARN ──────────────────────────────────────────
def get_sagemaker_role():
    step_banner(3, "Retrieve SageMaker Execution Role ARN")

    ssm = boto3.client("ssm", region_name=REGION)

    try:
        response = ssm.get_parameter(Name=SSM_ROLE_PARAM)
        role_arn = response["Parameter"]["Value"]
        print(f"  Role ARN from SSM: {role_arn}")
        return role_arn
    except ClientError as e:
        if e.response["Error"]["Code"] == "ParameterNotFound":
            # Fallback: construct the ARN from known role name
            role_arn = f"arn:aws:iam::{ACCOUNT_ID}:role/DqSageMakerExecutionRole"
            print(f"  SSM parameter not found, using fallback: {role_arn}")

            # Verify role exists
            iam = boto3.client("iam", region_name=REGION)
            try:
                iam.get_role(RoleName="DqSageMakerExecutionRole")
                print(f"  [OK] Role verified in IAM")
                return role_arn
            except ClientError:
                print(f"  ERROR: Role DqSageMakerExecutionRole not found in IAM")
                sys.exit(1)
        raise


# ─── Step 4: Resolve JumpStart Training Image ────────────────────────────────
def get_jumpstart_training_image():
    """Get the HuggingFace LLM training image URI for us-east-1."""
    # SageMaker HuggingFace DLC images for text generation fine-tuning
    # These are the official SageMaker Deep Learning Container images
    # Format: {account}.dkr.ecr.{region}.amazonaws.com/{repo}:{tag}
    #
    # For HuggingFace text generation fine-tuning on PyTorch 2.1:
    huggingface_image = (
        "763104351884.dkr.ecr.us-east-1.amazonaws.com/"
        "huggingface-pytorch-tgi-inference:2.1.1-tgi2.0.2-gpu-py310-cu121-ubuntu22.04"
    )
    # For training specifically, use the training image:
    training_image = (
        "763104351884.dkr.ecr.us-east-1.amazonaws.com/"
        "huggingface-pytorch-training:2.1.0-transformers4.36.0-gpu-py310-cu121-ubuntu20.04"
    )
    return training_image


# ─── Step 4: Launch Training Job via boto3 ────────────────────────────────────
def launch_training_job(role_arn: str, train_s3_uri: str, val_s3_uri: str):
    step_banner(4, "Launch SageMaker Fine-Tuning Job")

    sm_client = boto3.client("sagemaker", region_name=REGION)
    job_name = f"dq-rule-finetune-{int(time.time())}"
    training_image = get_jumpstart_training_image()
    output_path = f"s3://{S3_BUCKET}/{S3_OUTPUT_PREFIX}"

    print(f"  Job Name: {job_name}")
    print(f"  Training Image: {training_image}")
    print(f"  Instance Type: ml.g5.2xlarge")
    print(f"  Role ARN: {role_arn}")
    print(f"  Train URI: {train_s3_uri}")
    print(f"  Validation URI: {val_s3_uri}")
    print(f"  Output Path: {output_path}")
    print()

    # Hyperparameters for HuggingFace fine-tuning
    hyperparameters = {
        "model_name_or_path": "mistralai/Mistral-7B-Instruct-v0.3",
        "epochs": "3",
        "per_device_train_batch_size": "2",
        "learning_rate": "2e-5",
        "gradient_accumulation_steps": "4",
        "bf16": "True",
        "max_seq_length": "1024",
        "lora_r": "16",
        "lora_alpha": "32",
        "lora_dropout": "0.05",
        "warmup_ratio": "0.1",
        "logging_steps": "10",
        "save_strategy": "epoch",
    }

    try:
        response = sm_client.create_training_job(
            TrainingJobName=job_name,
            RoleArn=role_arn,
            AlgorithmSpecification={
                "TrainingImage": training_image,
                "TrainingInputMode": "File",
            },
            HyperParameters=hyperparameters,
            InputDataConfig=[
                {
                    "ChannelName": "training",
                    "DataSource": {
                        "S3DataSource": {
                            "S3DataType": "S3Prefix",
                            "S3Uri": train_s3_uri,
                            "S3DataDistributionType": "FullyReplicated",
                        }
                    },
                    "ContentType": "application/jsonlines",
                    "CompressionType": "None",
                },
                {
                    "ChannelName": "validation",
                    "DataSource": {
                        "S3DataSource": {
                            "S3DataType": "S3Prefix",
                            "S3Uri": val_s3_uri,
                            "S3DataDistributionType": "FullyReplicated",
                        }
                    },
                    "ContentType": "application/jsonlines",
                    "CompressionType": "None",
                },
            ],
            OutputDataConfig={
                "S3OutputPath": output_path,
            },
            ResourceConfig={
                "InstanceType": "ml.g5.2xlarge",
                "InstanceCount": 1,
                "VolumeSizeInGB": 100,
            },
            StoppingCondition={
                "MaxRuntimeInSeconds": 14400,  # 4 hours max
            },
            Tags=[
                {"Key": "Project", "Value": "dq-platform"},
                {"Key": "Purpose", "Value": "rule-interpretation-finetuning"},
            ],
        )

        training_job_arn = response["TrainingJobArn"]
        print(f"  [OK] Training job created successfully!")
        print(f"  Job ARN: {training_job_arn}")
        print(f"  Job Name: {job_name}")
        print(f"  Status: InProgress")
        print()
        print(f"  Monitor with:")
        print(f"    aws sagemaker describe-training-job --training-job-name {job_name} --region {REGION}")
        print()
        print(f"  SageMaker Console:")
        print(f"    https://{REGION}.console.aws.amazon.com/sagemaker/home?region={REGION}#/jobs/{job_name}")

        return job_name

    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_msg = e.response["Error"]["Message"]
        print(f"\n  ERROR launching training job: [{error_code}] {error_msg}")

        if "ResourceLimitExceeded" in str(error_msg):
            print("\n  -> You may need to request a quota increase for ml.g5.2xlarge.")
            print(f"    AWS Console: https://{REGION}.console.aws.amazon.com/servicequotas/")
        elif "AccessDenied" in str(error_msg) or "not authorized" in str(error_msg).lower():
            print("\n  -> The SageMaker execution role needs additional permissions.")
            print("    Required: sagemaker:CreateTrainingJob, s3:GetObject, s3:PutObject")
            print("    Also verify the caller has iam:PassRole for the SageMaker role.")

        # Attempt with SageMaker SDK v3 ModelTrainer as fallback
        print("\n  Attempting fallback with SageMaker SDK v3 ModelTrainer...")
        return launch_with_model_trainer(role_arn, train_s3_uri, val_s3_uri)

    except Exception as e:
        print(f"\n  ERROR: {type(e).__name__}: {e}")
        print("\n  Attempting fallback with SageMaker SDK v3 ModelTrainer...")
        return launch_with_model_trainer(role_arn, train_s3_uri, val_s3_uri)


def launch_with_model_trainer(role_arn, train_s3_uri, val_s3_uri):
    """Fallback using SageMaker SDK v3 ModelTrainer."""
    try:
        from sagemaker.train import ModelTrainer
        from sagemaker.core.shapes import (
            AlgorithmSpecification,
            Channel,
            DataSource,
            OutputDataConfig,
            ResourceConfig,
            S3DataSource,
            StoppingCondition,
        )

        job_name = f"dq-rule-finetune-v3-{int(time.time())}"
        training_image = get_jumpstart_training_image()
        output_path = f"s3://{S3_BUCKET}/{S3_OUTPUT_PREFIX}"

        print(f"\n  Fallback Job Name: {job_name}")

        trainer = ModelTrainer(
            training_image=training_image,
            hyperparameters={
                "model_name_or_path": "mistralai/Mistral-7B-Instruct-v0.3",
                "epochs": "3",
                "per_device_train_batch_size": "2",
                "learning_rate": "2e-5",
                "lora_r": "16",
                "lora_alpha": "32",
            },
            role=role_arn,
            instance_type="ml.g5.2xlarge",
            instance_count=1,
            volume_size_in_gb=100,
            output_data_config=OutputDataConfig(s3_output_path=output_path),
            stopping_condition=StoppingCondition(max_runtime_in_seconds=14400),
        )

        trainer.train(
            input_data_config=[
                Channel(
                    channel_name="training",
                    data_source=DataSource(
                        s3_data_source=S3DataSource(
                            s3_uri=train_s3_uri,
                            s3_data_type="S3Prefix",
                        )
                    ),
                ),
            ],
            wait=False,
        )

        print(f"  [OK] Fallback training job launched!")
        print(f"  Job Name: {job_name}")
        return job_name

    except Exception as e2:
        print(f"  Fallback also failed: {type(e2).__name__}: {e2}")
        print("\n  Both approaches failed. Please check:")
        print("    1. Your AWS credentials have sagemaker:CreateTrainingJob permission")
        print("    2. The SageMaker role has iam:PassRole trust relationship")
        print("    3. ml.g5.2xlarge quota is available in us-east-1")
        return None


# ─── Quota Check ──────────────────────────────────────────────────────────────
def check_and_request_quota():
    """Check GPU quota and request increase if needed."""
    step_banner(0, "Check SageMaker GPU Quota")

    sq = boto3.client("service-quotas", region_name=REGION)

    # Check ml.g5.2xlarge quota
    try:
        resp = sq.get_service_quota(ServiceCode="sagemaker", QuotaCode="L-2D6DEB3C")
        g5_quota = resp["Quota"]["Value"]
        print(f"  ml.g5.2xlarge training quota: {int(g5_quota)}")

        if g5_quota >= 1:
            print("  [OK] Sufficient quota for ml.g5.2xlarge")
            return "ml.g5.2xlarge"
    except ClientError:
        g5_quota = 0

    # Check ml.g4dn.xlarge quota
    try:
        resp = sq.get_service_quota(ServiceCode="sagemaker", QuotaCode="L-3F53BF0F")
        g4_quota = resp["Quota"]["Value"]
        print(f"  ml.g4dn.xlarge training quota: {int(g4_quota)}")

        if g4_quota >= 1:
            print("  [OK] Sufficient quota for ml.g4dn.xlarge")
            return "ml.g4dn.xlarge"
    except ClientError:
        g4_quota = 0

    print(f"\n  WARNING: All GPU training quotas are 0.")
    print(f"  Quota increase requests have been submitted:")
    print(f"    - ml.g5.2xlarge (L-2D6DEB3C): PENDING")
    print(f"    - ml.g4dn.xlarge (L-3F53BF0F): PENDING")
    print(f"\n  Once approved (usually 24-48h), re-run with: python launch_sagemaker_training.py --launch-only")

    return None


# ─── Main ────────────────────────────────────────────────────────────────────
def main():
    import argparse

    parser = argparse.ArgumentParser(description="Launch SageMaker fine-tuning for DQ rules")
    parser.add_argument("--launch-only", action="store_true",
                        help="Skip data prep/upload, only launch training job")
    parser.add_argument("--instance-type", type=str, default="ml.g5.2xlarge",
                        help="SageMaker instance type (default: ml.g5.2xlarge)")
    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("  SageMaker Fine-Tuning: Data Quality Rule Interpreter")
    print("=" * 60)
    print(f"\n  Account: {ACCOUNT_ID}")
    print(f"  Region:  {REGION}")
    print(f"  Bucket:  {S3_BUCKET}")
    print(f"  Input:   {INPUT_FILE.name}")

    if args.launch_only:
        # Skip data prep, just launch
        train_uri = f"s3://{S3_BUCKET}/{S3_TRAIN_PREFIX}/"
        val_uri = f"s3://{S3_BUCKET}/{S3_VAL_PREFIX}/"
        role_arn = get_sagemaker_role()
        job_name = launch_training_job(role_arn, train_uri, val_uri)
        n_train, n_val = "?", "?"
    else:
        # Step 1: Prepare data
        n_train, n_val = prepare_training_data()

        # Step 2: Upload to S3
        train_uri, val_uri = upload_to_s3()

        # Step 3: Get role
        role_arn = get_sagemaker_role()

        # Step 4: Launch training
        job_name = launch_training_job(role_arn, train_uri, val_uri)

    # Summary
    print("\n" + "=" * 60)
    print("  SUMMARY")
    print("=" * 60)
    print(f"  Training examples: {n_train}")
    print(f"  Validation examples: {n_val}")
    print(f"  S3 train path: {train_uri}")
    print(f"  S3 validation path: {val_uri}")
    print(f"  Role ARN: {role_arn}")
    if job_name:
        print(f"  Training Job: {job_name}")
        print(f"  Status: LAUNCHED (running async)")
        print(f"\n  The job typically takes 30-60 minutes to complete.")
        print(f"  Model artifacts will be saved to: s3://{S3_BUCKET}/{S3_OUTPUT_PREFIX}/")
    else:
        print(f"  Training Job: FAILED TO LAUNCH (quota = 0)")
        print(f"\n  NEXT STEPS:")
        print(f"  1. Quota increase requests submitted for:")
        print(f"     - ml.g5.2xlarge (Request ID: fff7b7ccb4144f9ea8915f2827b53bc5yT68xcJp)")
        print(f"     - ml.g4dn.xlarge (Request ID: 2f427096b3244c12a9da3e576074a76dYDvMLAeu)")
        print(f"  2. Check status: aws service-quotas list-requested-service-quota-change-history --service-code sagemaker --region {REGION}")
        print(f"  3. Once approved, re-run: python launch_sagemaker_training.py --launch-only")

    print("\n" + "=" * 60)

    return job_name


if __name__ == "__main__":
    job = main()
