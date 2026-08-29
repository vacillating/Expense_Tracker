import sys
from pathlib import Path

import pytest
from dotenv import load_dotenv

# 让 tests/ 下的用例能 `import schema`，不管 pytest 是从哪个目录被调用的。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 只在这里（测试代码）自动加载 .env，给 tests/test_parser_live.py 用——
# 跑 --run-live 需要 LLM_BASE_URL/LLM_API_KEY/LLM_MODEL，本地图省事放
# .env 里，不用每次手动 source。
#
# 故意不加进 parser.py 或任何生产代码：线上部署时环境变量是平台
# （Streamlit Cloud / 以后的 serverless）直接注入的，根本不会有 .env
# 文件——生产代码里放 load_dotenv() 只会多一次无意义的文件查找，还会
# 模糊"这个变量到底是从哪来的"。本地测试的便利属于测试代码，不该往
# 生产路径里渗。
load_dotenv()


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
