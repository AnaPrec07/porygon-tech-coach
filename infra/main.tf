/**
 * Terraform IaC for Tech Coach platform.
 *
 * Modules:
 *   - cloud_sql: PostgreSQL with pgvector
 *   - cloud_run: Backend + Frontend services
 *   - secret_manager: Application secrets
 *
 * Not included (managed separately or by default):
 *   - Artifact Registry (created manually first)
 *   - IAM service accounts (documented in README)
 *   - Cloud Build triggers (managed in Cloud Console)
 */

terraform {
  required_version = ">= 1.7"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
  backend "gcs" {
    bucket = "tech-coach-terraform-state"
    prefix = "terraform/state"
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# -------------------------------------------------------------------------
# Cloud SQL: PostgreSQL 16 with pgvector
# -------------------------------------------------------------------------
resource "google_sql_database_instance" "postgres" {
  name             = "tech-coach-postgres"
  database_version = "POSTGRES_16"
  region           = var.region

  settings {
    tier              = var.db_tier  # "db-f1-micro" for dev, "db-g1-small" for prod
    availability_type = var.environment == "production" ? "REGIONAL" : "ZONAL"

    backup_configuration {
      enabled            = true
      start_time         = "03:00"
      point_in_time_recovery_enabled = var.environment == "production"
      transaction_log_retention_days = 7
      backup_retention_settings {
        retained_backups = 7
      }
    }

    ip_configuration {
      ipv4_enabled    = false  # Private IP only
      private_network = google_compute_network.vpc.id
      enable_private_path_for_google_cloud_services = true
    }

    database_flags {
      name  = "shared_preload_libraries"
      value = "pg_stat_statements"
    }

    insights_config {
      query_insights_enabled  = true
      query_string_length     = 1024
      record_application_tags = true
      record_client_address   = false  # Privacy
    }
  }

  deletion_protection = var.environment == "production"
}

resource "google_sql_database" "app_db" {
  name     = "tech_coach"
  instance = google_sql_database_instance.postgres.name
}

resource "google_sql_user" "app_user" {
  name     = "tech_coach_app"
  instance = google_sql_database_instance.postgres.name
  password = random_password.db_password.result
}

resource "random_password" "db_password" {
  length  = 32
  special = false
}

# -------------------------------------------------------------------------
# VPC (private networking for Cloud SQL)
# -------------------------------------------------------------------------
resource "google_compute_network" "vpc" {
  name                    = "tech-coach-vpc"
  auto_create_subnetworks = true
}

resource "google_compute_global_address" "private_ip_range" {
  name          = "tech-coach-private-ip"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 20
  network       = google_compute_network.vpc.id
}

resource "google_service_networking_connection" "private_vpc" {
  network                 = google_compute_network.vpc.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.private_ip_range.name]
}

# -------------------------------------------------------------------------
# Secret Manager
# -------------------------------------------------------------------------
resource "google_secret_manager_secret" "db_url" {
  secret_id = "tech-coach-db-url"
  replication { auto {} }
}

resource "google_secret_manager_secret_version" "db_url" {
  secret = google_secret_manager_secret.db_url.id
  secret_data = (
    "postgresql+asyncpg://tech_coach_app:${random_password.db_password.result}"
    "@${google_sql_database_instance.postgres.private_ip_address}/tech_coach"
  )
}

resource "google_secret_manager_secret" "app_secret_key" {
  secret_id = "tech-coach-secret-key"
  replication { auto {} }
}

# google_client_id, google_client_secret, allowed_user_email
# are created manually and stored in Secret Manager out-of-band
# to avoid storing OAuth credentials in Terraform state.

# -------------------------------------------------------------------------
# Cloud Run: Backend (FastAPI)
# -------------------------------------------------------------------------
resource "google_cloud_run_v2_service" "backend" {
  name     = "tech-coach-api"
  location = var.region

  template {
    service_account = google_service_account.cloud_run_sa.email

    scaling {
      min_instance_count = 0
      max_instance_count = 3
    }

    containers {
      image = "${var.region}-docker.pkg.dev/${var.project_id}/tech-coach/backend:latest"

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
        cpu_idle = true  # Only charge for CPU during request handling
      }

      env {
        name  = "APP_ENV"
        value = var.environment
      }
      env {
        name  = "GCP_PROJECT_ID"
        value = var.project_id
      }
      env {
        name  = "VERTEX_AI_LOCATION"
        value = var.region
      }

      # Secrets injected at runtime
      env {
        name = "DATABASE_URL"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.db_url.secret_id
            version = "latest"
          }
        }
      }

      liveness_probe {
        http_get { path = "/health" }
        initial_delay_seconds = 15
        period_seconds        = 30
      }
    }

    vpc_access {
      connector = google_vpc_access_connector.connector.id
      egress    = "PRIVATE_RANGES_ONLY"
    }
  }

  depends_on = [google_project_service.apis]
}

# Restrict backend access (only frontend service can call it)
resource "google_cloud_run_v2_service_iam_binding" "backend_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.backend.name
  role     = "roles/run.invoker"
  members  = ["serviceAccount:${google_service_account.cloud_run_sa.email}"]
}

# -------------------------------------------------------------------------
# VPC Access Connector (Cloud Run → Cloud SQL private IP)
# -------------------------------------------------------------------------
resource "google_vpc_access_connector" "connector" {
  name          = "tech-coach-connector"
  region        = var.region
  network       = google_compute_network.vpc.name
  ip_cidr_range = "10.8.0.0/28"
  min_instances = 2
  max_instances = 3
}

# -------------------------------------------------------------------------
# Service Account for Cloud Run
# -------------------------------------------------------------------------
resource "google_service_account" "cloud_run_sa" {
  account_id   = "tech-coach"
  display_name = "Tech Coach Cloud Run Service Account"
}

resource "google_project_iam_member" "vertex_ai_user" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.cloud_run_sa.email}"
}

resource "google_project_iam_member" "secret_accessor" {
  project = var.project_id
  role    = "roles/secretmanager.secretAccessor"
  member  = "serviceAccount:${google_service_account.cloud_run_sa.email}"
}

resource "google_project_iam_member" "cloud_logging" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.cloud_run_sa.email}"
}

resource "google_project_iam_member" "cloud_trace" {
  project = var.project_id
  role    = "roles/cloudtrace.agent"
  member  = "serviceAccount:${google_service_account.cloud_run_sa.email}"
}

# -------------------------------------------------------------------------
# Enable required APIs
# -------------------------------------------------------------------------
locals {
  required_apis = [
    "run.googleapis.com",
    "sqladmin.googleapis.com",
    "servicenetworking.googleapis.com",
    "vpcaccess.googleapis.com",
    "secretmanager.googleapis.com",
    "aiplatform.googleapis.com",
    "logging.googleapis.com",
    "cloudtrace.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "redis.googleapis.com",
  ]
}

resource "google_project_service" "apis" {
  for_each                   = toset(local.required_apis)
  service                    = each.value
  disable_dependent_services = false
}
