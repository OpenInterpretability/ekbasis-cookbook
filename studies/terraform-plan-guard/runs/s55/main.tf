terraform {
  required_providers {
    docker     = { source = "kreuzwerker/docker", version = "~> 3.0" }
    postgresql = { source = "cyrilgdn/postgresql", version = "~> 1.25" }
    local      = { source = "hashicorp/local", version = "~> 2.5" }
    random     = { source = "hashicorp/random", version = "~> 3.6" }
    null       = { source = "hashicorp/null", version = "~> 3.2" }
  }
}
provider "docker" { host = "unix://$HOME/.docker/run/docker.sock" }
provider "postgresql" {
  host     = "127.0.0.1"
  port     = 47432
  username = "postgres"
  password = "tfgpass"
  sslmode  = "disable"
}
resource "postgresql_role" "app" {
  name     = "s55_app"
  login    = true
  password = "apppw"
}
resource "postgresql_database" "app" {
  name  = "s55_app"
  owner = postgresql_role.app.name
}
resource "postgresql_role" "reader" {
  name     = "s55_reader"
  login    = true
  password = "readerpw"
}
resource "postgresql_grant" "reader" {
  database    = postgresql_database.app.name
  role        = postgresql_role.reader.name
  schema      = "public"
  object_type = "table"
  objects     = ["app_t"]
  privileges  = ["SELECT"]
}
