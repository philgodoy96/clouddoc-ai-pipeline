resource "aws_s3_bucket" "documents" {
  bucket        = local.documents_bucket_name
  force_destroy = false

  tags = {
    Name       = local.documents_bucket_name
    BucketRole = "document-source"
  }
}

resource "aws_s3_bucket_public_access_block" "documents" {
  bucket = aws_s3_bucket.documents.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "documents" {
  bucket = aws_s3_bucket.documents.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "documents" {
  bucket = aws_s3_bucket.documents.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "documents" {
  bucket = aws_s3_bucket.documents.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "documents" {
  bucket = aws_s3_bucket.documents.id

  depends_on = [
    aws_s3_bucket_versioning.documents,
  ]

  rule {
    id     = "documents-retention"
    status = "Enabled"

    filter {
      prefix = "documents/"
    }

    expiration {
      days = 30
    }

    noncurrent_version_expiration {
      noncurrent_days = 30
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }
}

resource "aws_s3_bucket_notification" "documents" {
  bucket = aws_s3_bucket.documents.id

  queue {
    id            = "document-upload-created"
    queue_arn     = aws_sqs_queue.processing.arn
    events        = ["s3:ObjectCreated:*"]
    filter_prefix = "documents/"
    filter_suffix = "source.txt"
  }

  depends_on = [
    aws_sqs_queue_policy.processing_s3_publish,
  ]
}