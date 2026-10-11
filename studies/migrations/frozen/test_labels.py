import random, pgexec as X
from sqlsplit import split_sql
BASE = """
CREATE TYPE status AS ENUM ('a','b','c');
CREATE TABLE users (id serial PRIMARY KEY, email text UNIQUE NOT NULL, active boolean NOT NULL DEFAULT true, nick varchar(8), st status, score int);
CREATE TABLE posts (id uuid PRIMARY KEY, user_id int NOT NULL REFERENCES users(id) ON DELETE CASCADE, body text, pinned boolean);
CREATE TABLE tags (id bigserial PRIMARY KEY, label text);
INSERT INTO tags (id, label) VALUES (1, 'system-default-tag'), (2, 'system-other');
CREATE TABLE post_tags (post_id uuid REFERENCES posts(id), tag_id bigint REFERENCES tags(id), PRIMARY KEY (post_id, tag_id));
"""
CASES = {
 "drop_col": ("ALTER TABLE users DROP COLUMN email;", True),
 "copy_then_drop": ("ALTER TABLE users ADD COLUMN mail text; UPDATE users SET mail = email; ALTER TABLE users DROP COLUMN email;", False),
 "rename_col": ("ALTER TABLE users RENAME COLUMN email TO mail;", False),
 "delete_none": ("DELETE FROM users WHERE false;", False),
 "set_not_null": ("ALTER TABLE users ALTER COLUMN score SET NOT NULL;", False),
 "drop_bool": ("ALTER TABLE users DROP COLUMN active;", True),
 "drop_bool_post": ("ALTER TABLE posts DROP COLUMN pinned;", True),
 "rename_table": ("ALTER TABLE users RENAME TO accounts;", False),
 "move_table": ("CREATE TABLE t2 (id int, email text, active boolean, nick varchar(8), st status, score int); INSERT INTO t2 SELECT id,email,active,nick,st,score FROM users; ALTER TABLE posts DROP CONSTRAINT posts_user_id_fkey; DROP TABLE users;", False),
 "int_bigint": ("ALTER TABLE users ALTER COLUMN score TYPE bigint;", False),
 "shrink": ("ALTER TABLE users ALTER COLUMN email TYPE varchar(5);", False),
 "drop_join": ("DROP TABLE post_tags;", True),
 "cascade_delete": ("DELETE FROM users WHERE id IN (SELECT id FROM users LIMIT 1);", True),
 "update_enum": ("UPDATE users SET st = 'a';", True),
 "backfill_nulls": ("UPDATE users SET score = 0 WHERE score IS NULL; ALTER TABLE users ALTER COLUMN score SET NOT NULL;", False),
 "drop_fk_col": ("ALTER TABLE posts DROP COLUMN user_id;", True),
 "del_fixed_row": ("DELETE FROM post_tags WHERE tag_id = 1; DELETE FROM tags WHERE id = 1;", True),
 "upd_fixed_row": ("UPDATE tags SET label = 'renamed-tag' WHERE id = 2;", True),
 "noop_fixed": ("UPDATE tags SET label = label WHERE id = 2;", False),
 "move_to_child": ("CREATE TABLE pin (post_id uuid PRIMARY KEY REFERENCES posts(id), pinned boolean); INSERT INTO pin SELECT id, pinned FROM posts WHERE pinned IS NOT NULL; ALTER TABLE posts DROP COLUMN pinned;", False),
 "reverse_fk": ("ALTER TABLE users ADD COLUMN post_id uuid; UPDATE users u SET post_id = (SELECT p.id FROM posts p WHERE p.user_id = u.id LIMIT 1); ALTER TABLE posts DROP COLUMN user_id;", True),
 "add_notnull": ("ALTER TABLE users ADD COLUMN x int NOT NULL;", False),
}
X.create_db("t_base")
X.apply_progression("t_base", split_sql(BASE))
for name,(mig,exp) in CASES.items():
    X.clone_db("t_base","t_seed"); cnt = X.seed("t_seed", random.Random(1))
    pre = X.snapshot("t_seed")
    res = X.run_statements("t_seed", split_sql(mig))
    post = X.snapshot("t_seed")
    L = X.loss_label(pre, post)
    fails = any(r["ok"] is False for r in res)
    print(f"{name:16s} lost={L['lost']!s:5} exp={exp!s:5} {'OK' if L['lost']==exp else 'XX'} fails={fails} {L['lost_detail'][:2]} {[r['error'] for r in res if r['error']][:1]}")
print(cnt)
