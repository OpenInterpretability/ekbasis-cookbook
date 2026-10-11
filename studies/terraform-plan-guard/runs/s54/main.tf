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
  name     = "s54_app"
  login    = true
  password = "apppw"
}
resource "postgresql_database" "app" {
  name  = "s54_app"
  owner = postgresql_role.app.name
}
resource "postgresql_grant" "pub" {
  database    = postgresql_database.app.name
  role        = "public"
  schema      = "public"
  object_type = "table"
  objects     = ["app_t"]
  privileges  = ["SELECT"]
}
