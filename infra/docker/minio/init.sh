#!/bin/sh
# Готовит локальный бакет по той же схеме доступа, что и Cloudflare R2:
#   variants/  — публичное чтение (раздаётся CDN)
#   originals/ — приватно (доступ только у backend по presigned URL)
set -e

mc alias set local http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD"
mc mb --ignore-existing "local/$S3_BUCKET"

cat > /tmp/policy.json <<POLICY
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {"AWS": ["*"]},
      "Action": ["s3:GetObject"],
      "Resource": [
        "arn:aws:s3:::$S3_BUCKET/products/*/variants/*",
        "arn:aws:s3:::$S3_BUCKET/content/*/variants/*"
      ]
    }
  ]
}
POLICY

mc anonymous set-json /tmp/policy.json "local/$S3_BUCKET"
echo "MinIO готов: бакет $S3_BUCKET, публичны только префиксы variants/"
