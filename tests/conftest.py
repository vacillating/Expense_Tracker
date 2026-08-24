import sys
from pathlib import Path

# 让 tests/ 下的用例能 `import schema`，不管 pytest 是从哪个目录被调用的。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
