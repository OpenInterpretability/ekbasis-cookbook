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
resource "docker_volume" "data" {
  name = "tfg-s36-data"
}
resource "docker_container" "cache" {
  name  = "tfg-s36-cache"
  image = "redis:7.4-alpine"
  env   = []
  ports {
    internal = 6379
    external = 47144
    ip       = "127.0.0.1"
  }
  volumes {
    volume_name    = docker_volume.data.name
    container_path = "/var/lib/redis"
  }
}
