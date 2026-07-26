resource "aws_dynamodb_table" "document_jobs" {
  name                        = local.document_jobs_table_name
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "PK"
  table_class                 = "STANDARD"
  deletion_protection_enabled = local.is_production
  stream_enabled              = false

  attribute {
    name = "PK"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }

  tags = {
    Name      = local.document_jobs_table_name
    TableRole = "authoritative-job-state"
  }
}