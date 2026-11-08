variable "project_id" {
  description = "A Google Cloud project used only for staging."
  type        = string
}

variable "region" {
  type    = string
  default = "asia-south1"
}

variable "alert_email" {
  type = string
}

variable "billing_account" {
  description = "Leave empty to skip the budget alerts."
  type        = string
  default     = ""
}

variable "budget_amount" {
  type    = number
  default = 5000
}

variable "budget_currency" {
  type    = string
  default = "INR"
}

variable "github_repo" {
  type    = string
  default = "Tarak-Ram/TheNewGuyInTheTown"
}

variable "db_deletion_protection" {
  type    = bool
  default = true
}

variable "google_client_id" {
  type    = string
  default = ""
}

variable "gemini_live_model" {
  type    = string
  default = "gemini-3.8-live"
}

variable "gemini_live_fallback_model" {
  type    = string
  default = "gemini-live-2.5-flash-native-audio"
}

variable "gemini_text_model" {
  type    = string
  default = ""
}

variable "image_tag" {
  type    = string
  default = "latest"
}
