# Eval harness: Superset pointed at the scratch database
import os
SQLALCHEMY_DATABASE_URI = os.environ["DATABASE_URL"]
SECRET_KEY = "eval-only-" + "x" * 40
