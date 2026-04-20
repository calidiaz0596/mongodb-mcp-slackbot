#!/usr/bin/env bash
set -euo pipefail

########################################
# CONFIGURE THESE VALUES
########################################

# AWS region to use
REGION="YOUR_AWS_REGION"

# VPC and Subnet (replace with your VPC)
VPC_ID="YOUR_VPC_ID"

# Public subnet (has internet gateway access)
SUBNET_ID="YOUR_SUBNET_ID"

# Your public IP (no /32 here; we'll append it)
MY_IP="YOUR_PUBLIC_IP"

# Security group name
SG_NAME="YOUR_SECURITY_GROUP_NAME"

# SSH Key Pair name (REQUIRED for SSH access)
KEY_NAME="YOUR_KEY_PAIR_NAME"   # Private key should be located at ~/.ssh/YOUR_KEY_PAIR_NAME.pem

# Instance profile WITH SSM access (optional; leave empty to skip)
INSTANCE_PROFILE_NAME=""   # Set to instance profile name if needed for SSM access, or leave empty

# OS choice: "ubuntu" (24.04) or "amazonlinux" (AL2023)
OS_TYPE="amazonlinux"

# Instance details
INSTANCE_TYPE="t3.medium"
INSTANCE_NAME="YOUR_INSTANCE_NAME"

########################################
# TAGS (RSC-compliant)
########################################

# owner: first.last (email handle)
OWNER_TAG="YOUR_EMAIL_HANDLE"

# expire-on: YYYY-MM-DD
EXPIRE_ON_TAG="YYYY-MM-DD"

# purpose: one of training|partner|opportunity|other
PURPOSE_TAG="YOUR_PURPOSE"

# noreap: true to prevent auto-reaper deleting it
NOREAP_TAG="true"

########################################
# RESOLVE AMI ID VIA SSM
########################################

echo "Resolving AMI for ${OS_TYPE} in ${REGION}..."

if [[ "${OS_TYPE}" == "ubuntu" ]]; then
  AMI_PARAM="/aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id"
elif [[ "${OS_TYPE}" == "amazonlinux" ]]; then
  AMI_PARAM="/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
else
  echo "Unsupported OS_TYPE: ${OS_TYPE} (use 'ubuntu' or 'amazonlinux')" >&2
  exit 1
fi

AMI_ID="$(aws ssm get-parameters \
  --region "${REGION}" \
  --names "${AMI_PARAM}" \
  --query 'Parameters[0].Value' \
  --output text)"

echo "Using AMI_ID=${AMI_ID}"

########################################
# CREATE OR USE EXISTING SECURITY GROUP
########################################

echo "Checking for existing security group ${SG_NAME} in VPC ${VPC_ID}..."

# Try to find existing security group
SG_ID="$(aws ec2 describe-security-groups \
  --region "${REGION}" \
  --filters "Name=group-name,Values=${SG_NAME}" "Name=vpc-id,Values=${VPC_ID}" \
  --query 'SecurityGroups[0].GroupId' \
  --output text 2>/dev/null || echo "")"

if [[ -n "${SG_ID}" && "${SG_ID}" != "None" ]]; then
  echo "Using existing security group: ${SG_ID}"
else
  echo "Creating new security group ${SG_NAME}..."
  SG_ID="$(aws ec2 create-security-group \
    --region "${REGION}" \
    --group-name "${SG_NAME}" \
    --description "SSH-only security group" \
    --vpc-id "${VPC_ID}" \
    --query 'GroupId' \
    --output text)"
  
  echo "Created security group: ${SG_ID}"
fi

# Allow SSH only from your IP (attempt to add; ignore if rule already exists)
echo "Authorizing SSH from ${MY_IP}/32..."
aws ec2 authorize-security-group-ingress \
  --region "${REGION}" \
  --group-id "${SG_ID}" \
  --protocol tcp \
  --port 22 \
  --cidr "${MY_IP}/32" 2>&1 | grep -v "InvalidPermission.Duplicate" || true

# Note: new SGs have an allow-all egress rule by default (all outbound allowed)

########################################
# BUILD TAG SPECIFICATIONS
########################################

TAG_SPEC_INSTANCE="ResourceType=instance,Tags=[\
{Key=Name,Value=${INSTANCE_NAME}},\
{Key=owner,Value=${OWNER_TAG}},\
{Key=expire-on,Value=${EXPIRE_ON_TAG}},\
{Key=purpose,Value=${PURPOSE_TAG}},\
{Key=noreap,Value=${NOREAP_TAG}}]"

# Also tag the root EBS volume the same way (optional but recommended)
TAG_SPEC_VOLUME="ResourceType=volume,Tags=[\
{Key=Name,Value=${INSTANCE_NAME}},\
{Key=owner,Value=${OWNER_TAG}},\
{Key=expire-on,Value=${EXPIRE_ON_TAG}},\
{Key=purpose,Value=${PURPOSE_TAG}},\
{Key=noreap,Value=${NOREAP_TAG}}]"

########################################
# RUN INSTANCE
########################################

echo "Launching ${INSTANCE_TYPE} in subnet ${SUBNET_ID}..."

RUN_ARGS=(
  aws ec2 run-instances
  --region "${REGION}"
  --image-id "${AMI_ID}"
  --instance-type "${INSTANCE_TYPE}"
  --subnet-id "${SUBNET_ID}"
  --security-group-ids "${SG_ID}"
  --tag-specifications "${TAG_SPEC_INSTANCE}" "${TAG_SPEC_VOLUME}"
  --associate-public-ip-address
  --count 1
)

# Attach SSH key pair if specified
if [[ -n "${KEY_NAME}" ]]; then
  echo "Using SSH key pair: ${KEY_NAME}"
  RUN_ARGS+=(--key-name "${KEY_NAME}")
else
  echo "Warning: No SSH key pair specified. You will not be able to SSH into this instance."
fi

# Attach IAM instance profile for SSM if specified
if [[ -n "${INSTANCE_PROFILE_NAME}" ]]; then
  RUN_ARGS+=(--iam-instance-profile "Name=${INSTANCE_PROFILE_NAME}")
fi

INSTANCE_ID="$("${RUN_ARGS[@]}" \
  --query 'Instances[0].InstanceId' \
  --output text)"

echo "Launched instance: ${INSTANCE_ID}"

# Show public DNS/IP once available
echo "Describing instance networking..."
aws ec2 describe-instances \
  --region "${REGION}" \
  --instance-ids "${INSTANCE_ID}" \
  --query 'Reservations[0].Instances[0].{PublicDnsName:PublicDnsName,PublicIp:PublicIpAddress,PrivateIp:PrivateIpAddress}' \
  --output table

echo "Done. Instance ${INSTANCE_ID} created with required tags and restricted SSH access."