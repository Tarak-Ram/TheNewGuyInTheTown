variable "project_id" {
  description = "The Google Cloud project for this environment. Use a separate project per environment."
  type        = string
}

variable "region" {
  description = "Region for everything. Check that the Gemini Live API is offered here before relying on it."
  type        = string
  default     = "asia-south1"
}

variable "environment" {
  description = "Short environment name, such as staging."
  type        = string
}

variable "name" {
  description = "Prefix for resource names."
  type        = string
  default     = "nguit"
}

variable "alert_email" {
  description = "Where alerts and budget warnings are sent."
  type        = string
}

variable "billing_account" {
  description = "Billing account id (like 0123AB-456CDE-789FGH) for budget alerts. Leave empty to skip the budget."
  type        = string
  default     = ""
}

variable "budget_amount" {
  description = "Monthly budget, in the billing account's currency. Alerts fire at 50%, 90% and 100%, and on forecast."
  type        = number
  default     = 5000
}

variable "budget_currency" {
  description = "Must match the billing account's currency."
  type        = string
  default     = "INR"
}

variable "github_repo" {
  description = "GitHub repository allowed to deploy, as owner/name. Deploys come only from its main branch."
  type        = string
  default     = "Tarak-Ram/TheNewGuyInTheTown"
}

# -- database ----------------------------------------------------------------------------------
variable "db_tier" {
  description = "Cloud SQL machine size. This is the main fixed cost, so keep it small in staging."
  type        = string
  default     = "db-f1-micro"
}

variable "db_availability" {
  description = "ZONAL for staging. REGIONAL (high availability) for production."
  type        = string
  default     = "ZONAL"
}

variable "db_deletion_protection" {
  description = "Stops the database being deleted by accident. Turn off only to tear staging down."
  type        = bool
  default     = true
}

# -- services ----------------------------------------------------------------------------------
variable "image_tag" {
  description = "Image tag used when the services are first created. Later deploys are done by the deploy script, which Terraform then leaves alone."
  type        = string
  default     = "latest"
}

variable "max_instances" {
  description = "Upper limit per service, which also caps cost."
  type        = number
  default     = 3
}

variable "gateway_min_instances" {
  description = "The voice gateway keeps this many instances warm, so a call never waits for a cold start."
  type        = number
  default     = 1
}

variable "demo_mode" {
  description = "Turns on the demo sign-in and labelled estimates. Never true in production."
  type        = bool
  default     = false
}

variable "google_client_id" {
  description = "Google OAuth client id for sign-in. It is public, so it is not a secret."
  type        = string
  default     = ""
}

variable "gemini_live_model" {
  description = "Confirm this model id works in your project before the first call."
  type        = string
  default     = "gemini-3.8-live"
}

variable "gemini_live_fallback_model" {
  type    = string
  default = "gemini-live-2.5-flash-native-audio"
}

variable "gemini_text_model" {
  description = "Exact Gemini Flash model id from the console. Empty means the app uses its built-in fallbacks."
  type        = string
  default     = ""
}
