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
resource "random_id" "sfx" {
  byte_length = 2
  keepers = { image = "nginx:1.26-alpine" }
}
resource "docker_container" "web" {
  name  = "tfg-s16-web-${random_id.sfx.hex}"
  image = "nginx:1.26-alpine"
  ports {
    internal = 80
    external = 47064
    ip       = "127.0.0.1"
  }
  lifecycle {
    create_before_destroy = true
  }
}
