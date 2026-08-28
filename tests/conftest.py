import sys
from pathlib import Path

import pytest

# 让 tests/ 下的用例能 `import schema`，不管 pytest 是从哪个目录被调用的。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def pytest_addoption(parser):
    parser.addoption(
        "--run-live",
        action="store_true",
        default=False,
        help="真的调 LLM API 跑 @pytest.mark.live 的用例（需要配好 "
             "LLM_BASE_URL/LLM_API_KEY/LLM_MODEL）。不加这个参数时这些用例全部跳过。",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-live"):
        return  # 显式要求跑，不跳过
    skip_live = pytest.mark.skip(reason="需要真实 LLM API，默认跳过——加 --run-live 才跑")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)
