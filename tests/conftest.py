import os, sys, tempfile
os.environ["FINN_DATA_MODE"] = "sample"
os.environ["FINN_DATA_DIR"] = tempfile.mkdtemp(prefix="finn-test-")
for k in ("FINN_LLM_KEY", "FINN_MODEL_CHEAP", "FINN_MODEL_STRONG"):
    os.environ.pop(k, None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
