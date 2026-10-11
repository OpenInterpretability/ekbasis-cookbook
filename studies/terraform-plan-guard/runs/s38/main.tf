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
resource "random_pet" "vol" {
  keepers = { generation = "2" }
}
resource "docker_volume" "data" {
  name = "tfg-s38-${random_pet.vol.id}"
}
resource "docker_container" "db" {
  name  = "tfg-s38-db"
  image = "postgres:17-alpine"
  env   = ["POSTGRES_PASSWORD=apppass"]
  ports {
    internal = 5432
    external = 47152
    ip       = "127.0.0.1"
  }
  volumes {
    volume_name    = docker_volume.data.name
    container_path = "/var/lib/postgresql/data"
  }
}
