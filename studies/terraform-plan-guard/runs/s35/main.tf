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
resource "docker_container" "cache" {
  name  = "tfg-s35-cache"
  image = "redis:7-alpine"
  env   = ["TZ=UTC"]
  ports {
    internal = 6379
    external = 47140
    ip       = "127.0.0.1"
  }
  volumes {
    host_path      = "$STUDY_DIR/runs/s35/bind"
    container_path = "/data"
  }
}
