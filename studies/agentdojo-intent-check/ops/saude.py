import os, sys, openai
from ekbasis import intent_check
try:
    c = openai.OpenAI(base_url=os.environ["GLM_BASE_URL"], timeout=60, max_retries=0)
    r = c.chat.completions.create(model="glm-5.3-flash", messages=[{"role": "user", "content": "ok?"}], max_tokens=5, reasoning_effort="low")
    v = intent_check("What's my balance?", [], {"name": "get_balance", "input": {}})
    print("ok", v.verdict); sys.exit(0)
except Exception as e:
    print("falha", type(e).__name__, str(e)[:120]); sys.exit(1)
