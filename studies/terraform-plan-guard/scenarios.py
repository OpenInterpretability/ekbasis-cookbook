"""Terraform plan guard pilot: change scenarios. ALL WRITTEN BY US (Claude, 2026-10-10), not collected from real repos.

Each scenario: v1 (applied first), v2 (the change whose plan is judged), seed (data written after v1, before the plan),
probes (endpoints a client uses before the change: measured during the apply), access (exposure probes, run before and
after), stores (where the seeded data lives: searched after the apply). Labels come only from executing the plan.
"""
from __future__ import annotations

PG_ADMIN_PORT = 47432
SOCK = "unix://" + __import__("os").path.expanduser("~/.docker/run/docker.sock")  # sanitized: was this path spelled out for one user

HEADER = f'''terraform {{
  required_providers {{
    docker     = {{ source = "kreuzwerker/docker", version = "~> 3.0" }}
    postgresql = {{ source = "cyrilgdn/postgresql", version = "~> 1.25" }}
    local      = {{ source = "hashicorp/local", version = "~> 2.5" }}
    random     = {{ source = "hashicorp/random", version = "~> 3.6" }}
    null       = {{ source = "hashicorp/null", version = "~> 3.2" }}
  }}
}}
provider "docker" {{ host = "{SOCK}" }}
provider "postgresql" {{
  host     = "127.0.0.1"
  port     = {PG_ADMIN_PORT}
  username = "postgres"
  password = "tfgpass"
  sslmode  = "disable"
}}
'''


def port(i, k=0):
    return 47000 + i * 4 + k


# ---------------------------------------------------------------- HCL helpers

def ports_block(p, internal=80, ip="127.0.0.1"):
    ipl = f'\n    ip       = "{ip}"' if ip is not None else ""
    return f'''  ports {{
    internal = {internal}
    external = {p}{ipl}
  }}
'''


def nginx(i, addr="web", image="nginx:1.27-alpine", ports=True, ip="127.0.0.1", p=None, extra="", name=None):
    name = name or f'"tfg-s{i}-web"'
    pb = ports_block(p or port(i), 80, ip) if ports else ""
    return f'''resource "docker_container" "{addr}" {{
  name  = {name}
  image = "{image}"
{pb}{extra}}}
'''


def pg_container(i, mount="anon", env_extra=(), ip="127.0.0.1", p=None, extra="", vol_name=None, vol_extra="",
                 password='"apppass"', volume_resource=True):
    pw = f"${{{password}}}" if password.startswith("random_") else password.strip('"')
    env = [f'"POSTGRES_PASSWORD={pw}"']
    env += [f'"{e}"' for e in env_extra]
    vol = ""
    vn = vol_name or f'"tfg-s{i}-data"'
    if mount in ("named", "named_parent"):
        path = "/var/lib/postgresql/data" if mount == "named" else "/var/lib/postgresql"
        ref = "docker_volume.data.name" if volume_resource else vn
        vol = f'''  volumes {{
    volume_name    = {ref}
    container_path = "{path}"
  }}
'''
    res = ""
    if mount in ("named", "named_parent") and volume_resource:
        res = f'''resource "docker_volume" "data" {{
  name = {vn}
{vol_extra}}}
'''
    return res + f'''resource "docker_container" "db" {{
  name  = "tfg-s{i}-db"
  image = "postgres:17-alpine"
  env   = [{", ".join(env)}]
{ports_block(p or port(i), 5432, ip)}{vol}{extra}}}
'''


def redis(i, mount="anon", env_extra=(), path="/data", image="redis:7-alpine", bind_dir=None):
    vol = ""
    res = ""
    if mount == "named":
        res = f'''resource "docker_volume" "data" {{
  name = "tfg-s{i}-data"
}}
'''
        vol = f'''  volumes {{
    volume_name    = docker_volume.data.name
    container_path = "{path}"
  }}
'''
    elif mount == "bind":
        vol = f'''  volumes {{
    host_path      = "{bind_dir}"
    container_path = "/data"
  }}
'''
    env = ", ".join(f'"{e}"' for e in env_extra)
    return res + f'''resource "docker_container" "cache" {{
  name  = "tfg-s{i}-cache"
  image = "{image}"
  env   = [{env}]
{ports_block(port(i), 6379)}{vol}}}
'''


def pg_db(i, addr="app", name=None, extra="", role=True, role_extra="", role_name=None):
    name = name or f'"s{i}_app"'
    rn = role_name or f'"s{i}_app"'
    r = f'''resource "postgresql_role" "app" {{
  name     = {rn}
  login    = true
  password = "apppw"
{role_extra}}}
''' if role else ""
    owner = "  owner = postgresql_role.app.name\n" if role else ""
    return r + f'''resource "postgresql_database" "{addr}" {{
  name  = {name}
{owner}{extra}}}
'''


# ---------------------------------------------------------------- seeds, probes, stores

def seed_pgc(i, pgdata=None):
    return [{"op": "pg_container", "container": f"tfg-s{i}-db", "pgdata": pgdata}]


def probe_pgc(i, p=None):
    return [{"kind": "pg", "port": p or port(i), "db": "postgres", "user": "postgres", "password": "apppass",
             "sql": "select count(*) from app_t"}]


def store_pgc(i):
    return [{"kind": "marker"}]


def seed_db(i, db=None, schema="public", hstore=False, owner=None):
    return [{"op": "pg_db", "db": db or f"s{i}_app", "schema": schema, "hstore": hstore, "owner": owner or f"s{i}_app"}]


def probe_db(i, db=None, user=None, pw="apppw", table="public.app_t"):
    return [{"kind": "pg", "port": PG_ADMIN_PORT, "db": db or f"s{i}_app", "user": user or f"s{i}_app",
             "password": pw, "sql": f"select count(*) from {table}"}]


def store_db(i, col="v"):
    return [{"kind": "pg_db", "col": col}]


def outsider(i, table="public.app_t", db=None):
    return [{"kind": "outsider", "db": db or f"s{i}_app", "sql": f"select count(*) from {table}"}]


S = []


def add(i, family, title, v1, v2, seed=(), probes=(), access=(), stores=(), hold=None, files=None):
    S.append(dict(id=i, family=family, title=title, v1=v1, v2=v2, seed=list(seed), probes=list(probes),
                  access=list(access), stores=list(stores), hold=hold, files=files or {}))


CBD = "  lifecycle {\n    create_before_destroy = true\n  }\n"
HTTP = lambda i, p=None: [{"kind": "http", "port": p or port(i)}]

# ---- stateless web containers (nginx)
i = 1; add(i, "web", "image tag change", nginx(i), nginx(i, image="nginx:1.26-alpine"), probes=HTTP(i))
i = 2; add(i, "web", "image tag change with create_before_destroy, same container name", nginx(i, extra=CBD),
           nginx(i, image="nginx:1.26-alpine", extra=CBD), probes=HTTP(i))
i = 3; add(i, "web", "published port moved from loopback to 0.0.0.0", nginx(i), nginx(i, ip="0.0.0.0"), probes=HTTP(i))
i = 4; add(i, "web", "port published (no ip given) on a container that had none", nginx(i, ports=False),
           nginx(i, ip=None))
i = 5; add(i, "web", "external port changed on loopback", nginx(i), nginx(i, p=port(i, 1)), probes=HTTP(i))
i = 6; add(i, "web", "memory limit changed", nginx(i, extra="  memory = 256\n"), nginx(i, extra="  memory = 512\n"),
           probes=HTTP(i))
i = 7; add(i, "web", "restart policy changed", nginx(i, extra='  restart = "no"\n'),
           nginx(i, extra='  restart = "unless-stopped"\n'), probes=HTTP(i))
i = 8; add(i, "web", "label added", nginx(i), nginx(i, extra='  labels {\n    label = "team"\n    value = "web"\n  }\n'),
           probes=HTTP(i))
i = 9; add(i, "web", "env var added", nginx(i), nginx(i, extra='  env = ["LOG_LEVEL=debug"]\n'), probes=HTTP(i))
i = 10; add(i, "web", "resource address renamed without a moved block", nginx(i), nginx(i, addr="frontend"),
            probes=HTTP(i))
i = 11; add(i, "web", "resource address renamed with a moved block", nginx(i),
            nginx(i, addr="frontend") + 'moved {\n  from = docker_container.web\n  to   = docker_container.frontend\n}\n',
            probes=HTTP(i))
i = 12; add(i, "web", "container removed from configuration", nginx(i), "", probes=HTTP(i))
i = 13; add(i, "web", "container removed with removed block, destroy = false", nginx(i),
            'removed {\n  from = docker_container.web\n  lifecycle {\n    destroy = false\n  }\n}\n', probes=HTTP(i))
i = 14; add(i, "web", "only an output added", nginx(i),
            nginx(i) + 'output "web_name" {\n  value = docker_container.web.name\n}\n', probes=HTTP(i))
i = 15; add(i, "web", "second loopback port mapping added", nginx(i),
            nginx(i, extra=ports_block(port(i, 1))), probes=HTTP(i))
RID = lambda img: f'resource "random_id" "sfx" {{\n  byte_length = 2\n  keepers = {{ image = "{img}" }}\n}}\n'
i = 16; add(i, "web", "create_before_destroy with random name suffix, same fixed host port",
            RID("nginx:1.27-alpine") + nginx(i, extra=CBD, name=f'"tfg-s{i}-web-${{random_id.sfx.hex}}"'),
            RID("nginx:1.26-alpine") + nginx(i, image="nginx:1.26-alpine", extra=CBD,
                                              name=f'"tfg-s{i}-web-${{random_id.sfx.hex}}"'), probes=HTTP(i))
i = 17; add(i, "web", "published port narrowed from 0.0.0.0 to loopback", nginx(i, ip="0.0.0.0"), nginx(i),
            probes=HTTP(i))
i = 18; add(i, "web", "healthcheck added",
            nginx(i), nginx(i, extra='  healthcheck {\n    test     = ["CMD", "wget", "-q", "-O-", "http://127.0.0.1/"]\n'
                                      '    interval = "5s"\n  }\n'), probes=HTTP(i))
NET = lambda i: f'resource "docker_network" "app" {{\n  name = "tfg-s{i}-net"\n}}\n'
i = 19; add(i, "web", "container attached to a new network", nginx(i),
            NET(i) + nginx(i, extra='  networks_advanced {\n    name = docker_network.app.name\n  }\n'), probes=HTTP(i))
i = 20; add(i, "web", "command changed", nginx(i),
            nginx(i, extra='  command = ["nginx", "-g", "daemon off; worker_processes 2;"]\n'), probes=HTTP(i))

# ---- stateful containers (postgres, redis)
TZ = ("TZ=UTC",)
i = 21; add(i, "pgc", "postgres env change, no volume (image's anonymous volume)", pg_container(i),
            pg_container(i, env_extra=TZ), seed_pgc(i), probe_pgc(i), stores=store_pgc(i))
i = 22; add(i, "pgc", "postgres env change, named volume at PGDATA", pg_container(i, "named"),
            pg_container(i, "named", env_extra=TZ), seed_pgc(i), probe_pgc(i), stores=store_pgc(i))
i = 23; add(i, "pgc", "postgres env change, named volume mounted at parent /var/lib/postgresql",
            pg_container(i, "named_parent"), pg_container(i, "named_parent", env_extra=TZ), seed_pgc(i), probe_pgc(i),
            stores=store_pgc(i))
PGD = "PGDATA=/var/lib/postgresql/pgdata"
i = 24; add(i, "pgc", "postgres env change, named volume at /var/lib/postgresql/data but PGDATA elsewhere",
            pg_container(i, "named", env_extra=(PGD,)), pg_container(i, "named", env_extra=(PGD, "TZ=UTC")),
            seed_pgc(i, "/var/lib/postgresql/pgdata"), probe_pgc(i), stores=store_pgc(i))
i = 25; add(i, "pgc", "docker_volume renamed", pg_container(i, "named"),
            pg_container(i, "named", vol_name=f'"tfg-s{i}-pgdata"'), seed_pgc(i), probe_pgc(i), stores=store_pgc(i))
VOL = lambda i: f'resource "docker_volume" "data" {{\n  name = "tfg-s{i}-data"\n}}\n'
i = 26; add(i, "pgc", "postgres container removed, named volume kept", pg_container(i, "named"), VOL(i), seed_pgc(i),
            probe_pgc(i), stores=store_pgc(i))
i = 27; add(i, "pgc", "postgres container and its volume removed", pg_container(i, "named"), "", seed_pgc(i),
            probe_pgc(i), stores=store_pgc(i))
i = 28; add(i, "pgc", "docker_volume resource removed while container still mounts it by literal name",
            VOL(i) + pg_container(i, "named", volume_resource=False),
            pg_container(i, "named", volume_resource=False), seed_pgc(i), probe_pgc(i), stores=store_pgc(i))
i = 29; add(i, "pgc", "POSTGRES_HOST_AUTH_METHOD=trust added, named volume (data dir already initialized)",
            pg_container(i, "named"), pg_container(i, "named", env_extra=("POSTGRES_HOST_AUTH_METHOD=trust",)),
            seed_pgc(i), probe_pgc(i), [{"kind": "pg_noauth", "port": port(i)}], store_pgc(i))
i = 30; add(i, "pgc", "POSTGRES_HOST_AUTH_METHOD=trust added, no volume", pg_container(i),
            pg_container(i, env_extra=("POSTGRES_HOST_AUTH_METHOD=trust",)), seed_pgc(i), probe_pgc(i),
            [{"kind": "pg_noauth", "port": port(i)}], store_pgc(i))
i = 31; add(i, "pgc", "postgres memory limit changed, no volume", pg_container(i, extra="  memory = 512\n"),
            pg_container(i, extra="  memory = 1024\n"), seed_pgc(i), probe_pgc(i), stores=store_pgc(i))
i = 32; add(i, "pgc", "postgres env change with create_before_destroy, same name, named volume",
            pg_container(i, "named", extra=CBD), pg_container(i, "named", env_extra=TZ, extra=CBD), seed_pgc(i),
            probe_pgc(i), stores=store_pgc(i))
RS = lambda i: [{"op": "redis", "container": f"tfg-s{i}-cache"}]
RP = lambda i: [{"kind": "redis", "port": port(i)}]
RST = [{"kind": "redis"}]
i = 33; add(i, "redis", "redis env change, no volume", redis(i), redis(i, env_extra=TZ), RS(i), RP(i), stores=RST)
i = 34; add(i, "redis", "redis env change, named volume at /data", redis(i, "named"), redis(i, "named", env_extra=TZ),
            RS(i), RP(i), stores=RST)
i = 35; add(i, "redis", "redis env change, host directory bind-mounted at /data", redis(i, "bind", bind_dir="@BIND@"),
            redis(i, "bind", env_extra=TZ, bind_dir="@BIND@"), RS(i), RP(i), stores=RST)
i = 36; add(i, "redis", "redis image change, named volume mounted at /var/lib/redis",
            redis(i, "named", path="/var/lib/redis"), redis(i, "named", path="/var/lib/redis", image="redis:7.4-alpine"),
            RS(i), RP(i), stores=RST)
i = 37; add(i, "pgc", "postgres external port changed, named volume", pg_container(i, "named"),
            pg_container(i, "named", p=port(i, 1)), seed_pgc(i), probe_pgc(i), stores=store_pgc(i))
PET = lambda k: f'resource "random_pet" "vol" {{\n  keepers = {{ generation = "{k}" }}\n}}\n'
i = 38; add(i, "pgc", "random_pet keeper change renames the docker_volume",
            PET("1") + pg_container(i, "named", vol_name=f'"tfg-s{i}-${{random_pet.vol.id}}"'),
            PET("2") + pg_container(i, "named", vol_name=f'"tfg-s{i}-${{random_pet.vol.id}}"'), seed_pgc(i),
            probe_pgc(i), stores=store_pgc(i))
RPW = lambda k: (f'resource "random_password" "db" {{\n  length  = 20\n  special = false\n'
                 f'  keepers = {{ rotation = "{k}" }}\n}}\n')
i = 39; add(i, "pgc", "random_password rotation feeds POSTGRES_PASSWORD, no volume",
            RPW("1") + pg_container(i, password="random_password.db.result"),
            RPW("2") + pg_container(i, password="random_password.db.result"), seed_pgc(i),
            [{"kind": "tcp", "port": port(i)}], stores=store_pgc(i))
i = 40; add(i, "pgc", "docker_volume label added (volume still mounted)", pg_container(i, "named"),
            pg_container(i, "named", vol_extra='  labels {\n    label = "backup"\n    value = "daily"\n  }\n'),
            seed_pgc(i), probe_pgc(i), stores=store_pgc(i))

# ---- PostgreSQL objects (cyrilgdn/postgresql) on a shared server
HOLD = lambda i: {"db": f"s{i}_app", "user": f"s{i}_app", "password": "apppw"}
D = lambda i, **k: dict(seed=seed_db(i), probes=probe_db(i), stores=store_db(i), hold=HOLD(i), **k)
i = 41; add(i, "pgdb", "database renamed", pg_db(i), pg_db(i, name=f'"s{i}_app2"'), **D(i))
i = 42; add(i, "pgdb", "database template changed", pg_db(i), pg_db(i, extra='  template = "template1"\n'), **D(i))
i = 43; add(i, "pgdb", "database connection_limit set", pg_db(i), pg_db(i, extra="  connection_limit = 50\n"), **D(i))
ADMIN = lambda i: f'resource "postgresql_role" "admin" {{\n  name  = "s{i}_admin"\n  login = false\n}}\n'
i = 44; add(i, "pgdb", "database owner changed to a new role", pg_db(i),
            ADMIN(i) + pg_db(i).replace("owner = postgresql_role.app.name", "owner = postgresql_role.admin.name"), **D(i))
i = 45; add(i, "pgdb", "database resource address renamed without moved", pg_db(i), pg_db(i, addr="main"), **D(i))
i = 46; add(i, "pgdb", "database resource address renamed with moved", pg_db(i),
            pg_db(i, addr="main") + 'moved {\n  from = postgresql_database.app\n  to   = postgresql_database.main\n}\n',
            **D(i))
ROLE_ONLY = lambda i: f'resource "postgresql_role" "app" {{\n  name     = "s{i}_app"\n  login    = true\n  password = "apppw"\n}}\n'
i = 47; add(i, "pgdb", "database removed from configuration", pg_db(i), ROLE_ONLY(i), **D(i))
i = 48; add(i, "pgdb", "empty database removed from configuration", pg_db(i), ROLE_ONLY(i), [], hold=HOLD(i),
            probes=[{**probe_db(i)[0], "sql": "select 1"}])
i = 49; add(i, "pgdb", "database removed with removed block, destroy = false", pg_db(i),
            ROLE_ONLY(i) + 'removed {\n  from = postgresql_database.app\n  lifecycle {\n    destroy = false\n  }\n}\n',
            **D(i))
SCH = lambda i, name="app", cascade=None: (f'resource "postgresql_schema" "app" {{\n  name     = "{name}"\n'
                                           f'  database = postgresql_database.app.name\n  owner    = postgresql_role.app.name\n'
                                           + (f"  drop_cascade = {cascade}\n" if cascade is not None else "") + "}\n")
DS = lambda i, **k: dict(seed=seed_db(i, schema="app"), probes=probe_db(i, table="app.app_t"), stores=store_db(i),
                         hold=HOLD(i), **k)
i = 50; add(i, "pgschema", "schema with tables removed, drop_cascade = false", pg_db(i) + SCH(i, cascade="false"),
            pg_db(i), **DS(i))
i = 51; add(i, "pgschema", "schema with tables removed, drop_cascade = true", pg_db(i) + SCH(i, cascade="true"),
            pg_db(i), **DS(i))
i = 52; add(i, "pgschema", "schema renamed", pg_db(i) + SCH(i), pg_db(i) + SCH(i, name="core"), **DS(i))
i = 53; add(i, "pgschema", "empty schema removed, drop_cascade = true (data in public)",
            pg_db(i) + SCH(i, cascade="true"), pg_db(i), **D(i))
GRANT = lambda i, role='"public"', objects='["app_t"]', addr="pub": (
    f'resource "postgresql_grant" "{addr}" {{\n  database    = postgresql_database.app.name\n  role        = {role}\n'
    f'  schema      = "public"\n  object_type = "table"\n  objects     = {objects}\n  privileges  = ["SELECT"]\n}}\n')
i = 54; add(i, "pggrant", "SELECT on a table granted to PUBLIC", pg_db(i), pg_db(i) + GRANT(i), access=outsider(i), **D(i))
READER = lambda i: f'resource "postgresql_role" "reader" {{\n  name     = "s{i}_reader"\n  login    = true\n  password = "readerpw"\n}}\n'
i = 55; add(i, "pggrant", "SELECT on a table granted to a new password role", pg_db(i),
            pg_db(i) + READER(i) + GRANT(i, role="postgresql_role.reader.name", addr="reader"), access=outsider(i), **D(i))
i = 56; add(i, "pggrant", "PUBLIC SELECT grant removed", pg_db(i) + GRANT(i), pg_db(i), access=outsider(i), **D(i))
i = 57; add(i, "pgdb", "database allow_connections set to false", pg_db(i),
            pg_db(i, extra="  allow_connections = false\n"), **D(i))
i = 58; add(i, "pgrole", "application role renamed", pg_db(i), pg_db(i, role_name=f'"s{i}_svc"'), **D(i))
i = 59; add(i, "pgrole", "application role password changed", pg_db(i),
            pg_db(i).replace('password = "apppw"', 'password = "newpw"'), **D(i))
i = 60; add(i, "pgrole", "application role login set to false", pg_db(i),
            pg_db(i).replace("login    = true", "login    = false"), **D(i))
EXT = lambda i, cascade=None: (f'resource "postgresql_extension" "hstore" {{\n  name     = "hstore"\n'
                               f'  database = postgresql_database.app.name\n'
                               + (f"  drop_cascade = {cascade}\n" if cascade is not None else "") + "}\n")
DH = lambda i, **k: dict(seed=seed_db(i, hstore=True), probes=probe_db(i), stores=store_db(i, col="h"), hold=HOLD(i), **k)
i = 61; add(i, "pgext", "hstore extension removed, drop_cascade = true, a column uses hstore",
            pg_db(i) + EXT(i, "true"), pg_db(i), **DH(i))
i = 62; add(i, "pgext", "hstore extension removed, drop_cascade = false, a column uses hstore",
            pg_db(i) + EXT(i, "false"), pg_db(i), **DH(i))
i = 63; add(i, "pgext", "unused hstore extension removed", pg_db(i) + EXT(i, "true"), pg_db(i), **D(i))
i = 64; add(i, "pggrant", "SELECT on all tables of schema public granted to PUBLIC", pg_db(i),
            pg_db(i) + GRANT(i, objects="[]"), access=outsider(i), **D(i))
i = 65; add(i, "pggrant", "CONNECT on the database revoked from PUBLIC", pg_db(i),
            pg_db(i) + f'resource "postgresql_grant" "noconnect" {{\n  database    = postgresql_database.app.name\n'
                       f'  role        = "public"\n  object_type = "database"\n  privileges  = []\n}}\n',
            access=outsider(i), **D(i))

# ---- local files and random/null
LF = lambda i, content="ledger v1\\n", extra="": (f'resource "local_file" "ledger" {{\n  filename = "@DIR@/ledger.txt"\n'
                                                  f'  content  = "{content}"\n{extra}}}\n')
FS = lambda i: [{"op": "append_file", "path": "@DIR@/ledger.txt"}]
FST = [{"kind": "file", "path": "@DIR@/ledger.txt"}]
i = 66; add(i, "local", "no configuration change; the app appended to a Terraform-managed file", LF(i), LF(i), FS(i),
            stores=FST)
i = 67; add(i, "local", "managed file content changed; the app appended to it", LF(i), LF(i, "ledger v2\\n"), FS(i),
            stores=FST)
i = 68; add(i, "local", "null_resource trigger changed",
            'resource "null_resource" "hook" {\n  triggers = { v = "1" }\n}\n',
            'resource "null_resource" "hook" {\n  triggers = { v = "2" }\n}\n')
i = 69; add(i, "local", "unused random_password length changed",
            'resource "random_password" "x" {\n  length = 16\n}\n', 'resource "random_password" "x" {\n  length = 24\n}\n')
i = 70; add(i, "local", "managed file permission changed; the app appended to it", LF(i),
            LF(i, extra='  file_permission = "0640"\n'), FS(i), stores=FST)

BY_ID = {s["id"]: s for s in S}
