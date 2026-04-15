# S3 Data Transfer Guide

Transfer data to Alliance infrastructure when direct access isn't possible (VPN restrictions).

## Workflow

```
Remote Server ──(internet)──→ S3 ←──(VPN)── AllianceMineDev
```

## Remote Server: Upload to S3

```bash
# Install AWS CLI
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
unzip awscliv2.zip && sudo ./aws/install

# Configure credentials (provided by Alliance admin)
aws configure
# Access Key ID: [provided]
# Secret Access Key: [provided]
# Region: us-east-1
# Output: json

# Upload files
aws s3 cp /path/to/data/ s3://BUCKET_NAME/mousemine/ --recursive

# Or single file
aws s3 cp file.tar.gz s3://BUCKET_NAME/mousemine/
```

## AllianceMineDev: Download from S3

```bash
ssh AllianceMineDev

# Download
aws s3 sync s3://BUCKET_NAME/mousemine/ ~/mousemine_data/
```

## Cost Estimate (100GB)

| Item | Cost |
|------|------|
| Storage (S3 Standard, 1 month) | $2.30 |
| Upload (data transfer IN) | Free |
| Download (same region us-east-1) | Free |
| Download (cross-region/internet) | ~$9.00 |
| API requests | ~$0.01 |
| **Total (same region)** | **~$2.50** |
| **Total (cross-region)** | **~$11.50** |

**Tip:** Delete data from S3 after transfer to avoid ongoing storage costs.

```bash
# Cleanup after transfer
aws s3 rm s3://BUCKET_NAME/mousemine/ --recursive
```
