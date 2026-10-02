provider "aws" {
  region = var.aws_region
}

# VPC and Networking
module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "5.0.0"

  name = "motorq-vpc"
  cidr = "10.0.0.0/16"

  azs             = ["${var.aws_region}a", "${var.aws_region}b", "${var.aws_region}c"]
  private_subnets = ["10.0.1.0/24", "10.0.2.0/24", "10.0.3.0/24"]
  public_subnets  = ["10.0.101.0/24", "10.0.102.0/24", "10.0.103.0/24"]

  enable_nat_gateway = true
  single_nat_gateway = false
}

# EKS Cluster for Stateless Services (API Gateway, Ingestion, Agent)
module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "19.15.3"

  cluster_name    = "motorq-eks-cluster"
  cluster_version = "1.27"
  vpc_id          = module.vpc.vpc_id
  subnet_ids      = module.vpc.private_subnets

  eks_managed_node_groups = {
    standard_nodes = {
      min_size     = 3
      max_size     = 10
      desired_size = 3
      instance_types = ["m5.large"]
    }
  }
}

# MSK (Managed Streaming for Apache Kafka)
resource "aws_msk_cluster" "motorq_kafka" {
  cluster_name           = "motorq-kafka-cluster"
  kafka_version          = "3.2.0"
  number_of_broker_nodes = 3

  broker_node_group_info {
    instance_type   = "kafka.m5.large"
    ebs_volume_size = 1000
    client_subnets  = module.vpc.private_subnets
    security_groups = [aws_security_group.kafka_sg.id]
  }
}

# RDS PostgreSQL (TimescaleDB alternative on AWS could be EC2 or specific RDS extensions)
resource "aws_db_instance" "motorq_postgres" {
  allocated_storage    = 100
  engine               = "postgres"
  engine_version       = "15.3"
  instance_class       = "db.m5.large"
  identifier           = "motorq-postgres"
  username             = var.db_user
  password             = var.db_password
  parameter_group_name = "default.postgres15"
  skip_final_snapshot  = true
  vpc_security_group_ids = [aws_security_group.db_sg.id]
  db_subnet_group_name   = aws_db_subnet_group.default.name
}

# ElastiCache Redis
resource "aws_elasticache_cluster" "motorq_redis" {
  cluster_id           = "motorq-redis"
  engine               = "redis"
  node_type            = "cache.m5.large"
  num_cache_nodes      = 1
  parameter_group_name = "default.redis7"
  engine_version       = "7.0"
  port                 = 6379
}

# S3 Bucket for Cold Storage (Parquet)
resource "aws_s3_bucket" "cold_storage" {
  bucket = "motorq-cold-storage-parquet"
}

# Note: DocumentDB (for MongoDB compatibility), OpenSearch (for Elasticsearch), 
# and EMR (for Spark) would also be provisioned here for a complete mirror.
