# Eval harness: NetBox configured from the environment (scratch database; Redis is never contacted by migrate)
import os
ALLOWED_HOSTS = ["*"]
DATABASES = {"default": {"NAME": os.environ["DB_NAME"], "USER": os.environ["DB_USER"],
                         "PASSWORD": os.environ["DB_PASSWORD"], "HOST": os.environ["DB_HOST"],
                         "PORT": os.environ["DB_PORT"], "CONN_MAX_AGE": 0}}
REDIS = {"tasks": {"HOST": "localhost", "PORT": 6379, "DATABASE": 0, "SSL": False},
         "caching": {"HOST": "localhost", "PORT": 6379, "DATABASE": 1, "SSL": False}}
SECRET_KEY = "eval-only-" + "x" * 60
