"""按阶段 manifest 运行真实检查命令，保存退出码与输出尾部。

用法：
  uv run python -m scripts.verify_stage P00 --mode offline
  uv run python -m scripts.verify_stage P01 --mode offline --report .runtime/reports/P01-offline.json
  uv run python -m scripts.verify_stage P01 --list

规则：退出码 0 才算通过；pytest 退出码 5（没有收集到测试）视为失败，
live/browser 没有检查时明确标记 not_run 并返回 2，不能伪装成通过。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT_ROOT = ROOT / ".runtime" / "reports"

# Windows console code pages may not encode a Unicode path inside a failing
# subprocess tail. Preserve the failure report instead of crashing the runner.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(errors="replace")

PYTHON = sys.executable


def _find_npm() -> str:
    found = shutil.which("npm")
    if found:
        return found
    return "npm.cmd" if os.name == "nt" else "npm"


NPM = _find_npm()


@dataclass(frozen=True)
class Check:
    name: str
    argv: tuple[str, ...]
    timeout_seconds: int = 600
    required: bool = True
    env: tuple[tuple[str, str], ...] = ()
    require_pytest_pass: bool = False

    @property
    def cwd(self) -> Path:
        return ROOT


P00_OFFLINE = (
    Check("db_init", (PYTHON, "-m", "scripts.init_db"), timeout_seconds=180),
    Check("compatibility", (PYTHON, "-m", "scripts.check_compatibility"), timeout_seconds=300),
    Check(
        "integration_tests",
        (PYTHON, "-m", "pytest", "tests/integration", "-q"),
        timeout_seconds=600,
    ),
    Check(
        "frontend_typecheck",
        (NPM, "--prefix", "frontend", "run", "typecheck"),
        timeout_seconds=300,
    ),
    Check(
        "frontend_tests",
        (NPM, "--prefix", "frontend", "run", "test", "--", "--run"),
        timeout_seconds=300,
    ),
    Check(
        "frontend_build",
        (NPM, "--prefix", "frontend", "run", "build"),
        timeout_seconds=600,
    ),
)

P02_OFFLINE = (
    Check("db_init", (PYTHON, "-m", "scripts.init_db"), timeout_seconds=180),
    Check("compatibility", (PYTHON, "-m", "scripts.check_compatibility"), timeout_seconds=300),
    Check(
        "seed",
        (PYTHON, "-m", "scripts.seed", "--reset"),
        timeout_seconds=300,
        env=(("MONGODB_DATABASE", "technologyagent_test_p02_verify"),),
    ),
    Check("unit_tests", (PYTHON, "-m", "pytest", "tests/unit", "-q"), timeout_seconds=300),
    Check(
        "integration_tests",
        (PYTHON, "-m", "pytest", "tests/integration", "-q"),
        timeout_seconds=900,
    ),
    Check(
        "frontend_typecheck",
        (NPM, "--prefix", "frontend", "run", "typecheck"),
        timeout_seconds=300,
    ),
    Check(
        "frontend_tests",
        (NPM, "--prefix", "frontend", "run", "test", "--", "--run"),
        timeout_seconds=300,
    ),
    Check(
        "frontend_build",
        (NPM, "--prefix", "frontend", "run", "build"),
        timeout_seconds=600,
    ),
    Check(
        "contract_check",
        (PYTHON, "-m", "scripts.export_contracts", "--check"),
        timeout_seconds=300,
    ),
)

P02_BROWSER = (
    Check(
        "frontend_e2e",
        (NPM, "--prefix", "frontend", "run", "test:e2e"),
        timeout_seconds=600,
    ),
)

P03_OFFLINE = (
    Check("db_init", (PYTHON, "-m", "scripts.init_db"), timeout_seconds=180),
    Check("compatibility", (PYTHON, "-m", "scripts.check_compatibility"), timeout_seconds=300),
    Check(
        "seed",
        (PYTHON, "-m", "scripts.seed", "--reset"),
        timeout_seconds=300,
        env=(("MONGODB_DATABASE", "technologyagent_test_p03_verify"),),
    ),
    Check("unit_tests", (PYTHON, "-m", "pytest", "tests/unit", "-q"), timeout_seconds=300),
    Check(
        "integration_tests",
        (PYTHON, "-m", "pytest", "tests/integration", "-q"),
        timeout_seconds=1200,
    ),
    Check("frontend_typecheck", (NPM, "--prefix", "frontend", "run", "typecheck"), timeout_seconds=300),
    Check("frontend_tests", (NPM, "--prefix", "frontend", "run", "test", "--", "--run"), timeout_seconds=300),
    Check("frontend_build", (NPM, "--prefix", "frontend", "run", "build"), timeout_seconds=600),
    Check("contract_check", (PYTHON, "-m", "scripts.export_contracts", "--check"), timeout_seconds=300),
)

P03_BROWSER = (
    Check(
        "frontend_e2e",
        (NPM, "--prefix", "frontend", "run", "test:e2e"),
        timeout_seconds=900,
    ),
)

P03_LIVE = (
    Check(
        "seed_live_db",
        (PYTHON, "-m", "scripts.seed", "--reset"),
        timeout_seconds=300,
        env=(("MONGODB_DATABASE", "technologyagent_test_p03_live"),),
    ),
    Check(
        "live_acceptance",
        (PYTHON, "-m", "pytest", "tests/live/test_readonly_agent.py", "-q", "-rs"),
        timeout_seconds=2400,
        env=(("RUN_LIVE_MODEL", "1"), ("MONGODB_DATABASE", "technologyagent_test_p03_live")),
    ),
)

P04_OFFLINE = (
    Check("db_init", (PYTHON, "-m", "scripts.init_db"), timeout_seconds=180),
    Check("compatibility", (PYTHON, "-m", "scripts.check_compatibility"), timeout_seconds=300),
    Check("seed", (PYTHON, "-m", "scripts.seed", "--reset"), timeout_seconds=300,
          env=(("MONGODB_DATABASE", "technologyagent_test_p04_verify"),)),
    Check("unit_tests", (PYTHON, "-m", "pytest", "tests/unit", "-q"), timeout_seconds=300),
    Check("integration_tests", (PYTHON, "-m", "pytest", "tests/integration", "-q"), timeout_seconds=1200),
    Check("frontend_typecheck", (NPM, "--prefix", "frontend", "run", "typecheck"), timeout_seconds=300),
    Check("frontend_tests", (NPM, "--prefix", "frontend", "run", "test", "--", "--run"), timeout_seconds=300),
    Check("frontend_build", (NPM, "--prefix", "frontend", "run", "build"), timeout_seconds=600),
    Check("contract_check", (PYTHON, "-m", "scripts.export_contracts", "--check"), timeout_seconds=300),
)

P04_BROWSER = (
    Check("seed", (PYTHON, "-m", "scripts.seed", "--reset"), timeout_seconds=300,
          env=(("MONGODB_DATABASE", "technologyagent_test_p04_browser"),)),
    Check("frontend_e2e", (NPM, "--prefix", "frontend", "run", "test:e2e", "--", "--workers=1"),
          timeout_seconds=900, env=(("P04_RESTART_BACKEND", "1"),)),
)

P04_LIVE = (
    Check("seed_live_db", (PYTHON, "-m", "scripts.seed", "--reset"), timeout_seconds=300,
          env=(("MONGODB_DATABASE", "technologyagent_test_p04_live"),)),
    Check("live_order_workflow", (PYTHON, "-m", "pytest", "tests/live/test_order_workflow.py", "-q", "-rs"),
          timeout_seconds=900,
          env=(("RUN_LIVE_MODEL", "1"), ("MONGODB_DATABASE", "technologyagent_test_p04_live"))),
)

P05_OFFLINE = (
    Check("db_init", (PYTHON, "-m", "scripts.init_db"), timeout_seconds=180),
    Check("compatibility", (PYTHON, "-m", "scripts.check_compatibility"), timeout_seconds=300),
    Check("seed", (PYTHON, "-m", "scripts.seed", "--reset"), timeout_seconds=300,
          env=(("MONGODB_DATABASE", "technologyagent_test_p05_verify"),)),
    Check("unit_tests", (PYTHON, "-m", "pytest", "tests/unit", "-q"), timeout_seconds=300),
    Check("integration_tests", (PYTHON, "-m", "pytest", "tests/integration", "-q"), timeout_seconds=1200),
    Check("frontend_typecheck", (NPM, "--prefix", "frontend", "run", "typecheck"), timeout_seconds=300),
    Check("frontend_tests", (NPM, "--prefix", "frontend", "run", "test", "--", "--run"), timeout_seconds=300),
    Check("frontend_build", (NPM, "--prefix", "frontend", "run", "build"), timeout_seconds=600),
    Check("contract_check", (PYTHON, "-m", "scripts.export_contracts", "--check"), timeout_seconds=300),
)

P05_BROWSER = (
    Check("seed", (PYTHON, "-m", "scripts.seed", "--reset"), timeout_seconds=300,
          env=(("MONGODB_DATABASE", "technologyagent_test_p05_browser"),)),
    Check("frontend_e2e", (NPM, "--prefix", "frontend", "run", "test:e2e", "--", "--workers=1"),
          timeout_seconds=900, env=(("P04_RESTART_BACKEND", "1"),
                                    ("MODEL_MODE", "fake"),
                                    ("MONGODB_DATABASE", "technologyagent_test_p05_browser"))),
)

P05_LIVE = (
    Check("seed_live_db", (PYTHON, "-m", "scripts.seed", "--reset"), timeout_seconds=300,
          env=(("MONGODB_DATABASE", "technologyagent_test_p05_live"),)),
    Check("live_p03_three_by_three", (PYTHON, "-m", "pytest", "tests/live/test_readonly_agent.py", "-q", "-rs"),
          timeout_seconds=2400,
          env=(("RUN_LIVE_MODEL", "1"), ("MONGODB_DATABASE", "technologyagent_test_p05_live"))),
    Check("live_p05_a04_revision", (PYTHON, "-m", "pytest", "tests/live/test_order_revision_a04.py", "-q", "-rs"),
          timeout_seconds=600,
          env=(("RUN_LIVE_MODEL", "1"), ("MODEL_MODE", "live"),
               ("MONGODB_DATABASE", "technologyagent_test_p05_live"))),
    Check("live_harness_inventory", (PYTHON, "-m", "pytest", "tests/live/test_harness_review.py", "-q", "-rs"),
          timeout_seconds=240,
          env=(("RUN_LIVE_MODEL", "1"), ("MONGODB_DATABASE", "technologyagent_test_p05_live"))),
    Check("live_order_workflow", (PYTHON, "-m", "pytest", "tests/live/test_order_workflow.py", "-q", "-rs"),
          timeout_seconds=900,
          env=(("RUN_LIVE_MODEL", "1"), ("MONGODB_DATABASE", "technologyagent_test_p05_live"))),
)

P06_OFFLINE = (
    Check("db_init", (PYTHON, "-m", "scripts.init_db"), timeout_seconds=180),
    Check("sandbox_image", ("docker", "build", "-t", "technologyagent-sandbox:0.1.0", "-f",
                             "backend/app/sandbox/Dockerfile", "backend/app/sandbox"), timeout_seconds=1800),
    Check("seed", (PYTHON, "-m", "scripts.seed", "--reset"), timeout_seconds=300,
          env=(("MONGODB_DATABASE", "technologyagent_test_p06_verify"),)),
    Check("unit_tests", (PYTHON, "-m", "pytest", "tests/unit", "-q", "--basetemp=.runtime/pytest-p07-unit"), timeout_seconds=400),
    Check("integration_tests", (PYTHON, "-m", "pytest", "tests/integration", "-q", "-rs"), timeout_seconds=1800,
          env=(("P06_REQUIRED", "1"),
               ("PYTEST_ADDOPTS", "--basetemp=.runtime/pytest-p06-fix2-offline"))),
    Check("frontend_typecheck", (NPM, "--prefix", "frontend", "run", "typecheck"), timeout_seconds=300),
    Check("frontend_tests", (NPM, "--prefix", "frontend", "run", "test", "--", "--run"), timeout_seconds=300),
    Check("frontend_build", (NPM, "--prefix", "frontend", "run", "build"), timeout_seconds=600),
    Check("contract_check", (PYTHON, "-m", "scripts.export_contracts", "--check"), timeout_seconds=300),
)

P06_BROWSER = (
    Check("seed", (PYTHON, "-m", "scripts.seed", "--reset"), timeout_seconds=300,
          env=(("MONGODB_DATABASE", "technologyagent_test_p06_browser"),)),
    Check("artifact_browser_e2e", (NPM, "--prefix", "frontend", "run", "test:e2e", "--", "--workers=1"),
          timeout_seconds=1200, env=(("MODEL_MODE", "fake"),
                                     ("MONGODB_DATABASE", "technologyagent_test_p06_browser"))),
)

P07_OFFLINE = (
    Check("db_init", (PYTHON, "-m", "scripts.init_db"), timeout_seconds=180,
          env=(("MONGODB_DATABASE", "technologyagent_test_p07_verify"),)),
    Check("compatibility", (PYTHON, "-m", "scripts.check_compatibility"), timeout_seconds=300,
          env=(("MONGODB_DATABASE", "technologyagent_test_p07_verify"),)),
    Check("seed", (PYTHON, "-m", "scripts.seed", "--reset"), timeout_seconds=300,
          env=(("MONGODB_DATABASE", "technologyagent_test_p07_verify"),)),
    Check("unit_tests", (PYTHON, "-m", "pytest", "tests/unit", "-q",
                          "--basetemp=.runtime/pytest-p07-unit"), timeout_seconds=400),
    Check("integration_tests", (PYTHON, "-m", "pytest", "tests/integration", "-q", "-rs"), timeout_seconds=1800,
          env=(("PYTEST_ADDOPTS", "--basetemp=.runtime/pytest-p07-offline"),)),
    Check("frontend_typecheck", (NPM, "--prefix", "frontend", "run", "typecheck"), timeout_seconds=300),
    Check("frontend_tests", (NPM, "--prefix", "frontend", "run", "test", "--", "--run"), timeout_seconds=300),
    Check("frontend_build", (NPM, "--prefix", "frontend", "run", "build"), timeout_seconds=600),
    Check("contract_check", (PYTHON, "-m", "scripts.export_contracts", "--check"), timeout_seconds=300),
)

P07_BROWSER = (
    Check("seed", (PYTHON, "-m", "scripts.seed", "--reset"), timeout_seconds=300,
          env=(("MONGODB_DATABASE", "technologyagent_test_p07_browser"),)),
    Check("frontend_e2e", (NPM, "--prefix", "frontend", "run", "test:e2e", "--", "--workers=1"),
          timeout_seconds=1200, env=(("MODEL_MODE", "fake"),
                                     ("MONGODB_DATABASE", "technologyagent_test_p07_browser"))),
)

P07_LIVE = (
    # Both the seed and the live API test must inherit the caller's explicit
    # isolated database so they inspect the same facts.
    Check("seed_live_db", (PYTHON, "-m", "scripts.seed", "--reset"), timeout_seconds=300),
    Check("live_specialist_flow", (PYTHON, "-m", "pytest", "tests/live/test_specialist_flow.py", "-q", "-rs"),
          timeout_seconds=1800,
          env=(("RUN_LIVE_MODEL", "1"), ("MODEL_MODE", "live"))),
)

P08_OFFLINE = (
    Check("db_init", (PYTHON, "-m", "scripts.init_db"), timeout_seconds=180,
          env=(("MONGODB_DATABASE", "technologyagent_test_p08_verify"),)),
    Check("compatibility", (PYTHON, "-m", "scripts.check_compatibility"), timeout_seconds=300,
          env=(("MONGODB_DATABASE", "technologyagent_test_p08_verify"),)),
    Check("seed", (PYTHON, "-m", "scripts.seed", "--reset"), timeout_seconds=300,
          env=(("MONGODB_DATABASE", "technologyagent_test_p08_verify"),)),
    Check("unit_tests", (PYTHON, "-m", "pytest", "tests/unit", "-q",
                          "--basetemp=.runtime/pytest-p08-unit"), timeout_seconds=600),
    Check("integration_tests", (PYTHON, "-m", "pytest", "tests/integration", "-q", "-rs"), timeout_seconds=2400,
          env=(("PYTEST_ADDOPTS", "--basetemp=.runtime/pytest-p08-offline"),)),
    Check("frontend_typecheck", (NPM, "--prefix", "frontend", "run", "typecheck"), timeout_seconds=300),
    Check("frontend_tests", (NPM, "--prefix", "frontend", "run", "test", "--", "--run"), timeout_seconds=300),
    Check("frontend_build", (NPM, "--prefix", "frontend", "run", "build"), timeout_seconds=600),
    Check("contract_check", (PYTHON, "-m", "scripts.export_contracts", "--check"), timeout_seconds=300),
)

P08_BROWSER = (
    Check("seed", (PYTHON, "-m", "scripts.seed", "--reset"), timeout_seconds=300,
          env=(("MONGODB_DATABASE", "technologyagent_test_p08_browser"),)),
    Check("frontend_e2e", (NPM, "--prefix", "frontend", "run", "test:e2e", "--",
                           "--grep", "generic business proposal", "--workers=1"),
          timeout_seconds=1500, env=(("MODEL_MODE", "fake"),
              ("MONGODB_DATABASE", "technologyagent_test_p08_browser"))),
)

P08_LIVE = (
    Check("live_erp_readonly", (PYTHON, "-m", "pytest", "tests/live/test_erp_readonly.py", "-q", "-rs"),
          timeout_seconds=300, env=(("MONGODB_DATABASE", "technologyagent_test_p08_live"),)),
    Check("live_erp_write", (PYTHON, "-m", "pytest", "tests/live/test_erp_write.py", "-q", "-rs"),
          timeout_seconds=600, env=(("MONGODB_DATABASE", "technologyagent_test_p08_live"),)),
)

P09_OFFLINE = (
    Check("compatibility", (PYTHON, "-m", "scripts.check_compatibility"), timeout_seconds=300,
          env=(("MONGODB_DATABASE", "technologyagent_test_p09_verify"),)),
    Check("seed", (PYTHON, "-m", "scripts.seed", "--reset"), timeout_seconds=300,
          env=(("MONGODB_DATABASE", "technologyagent_test_p09_verify"),)),
    Check("unit_and_integration", (PYTHON, "-m", "pytest", "tests/unit", "tests/integration", "-q", "-rs"),
          timeout_seconds=2400, env=(("PYTEST_ADDOPTS", "--basetemp=.runtime/pytest-p09-offline"),)),
    Check("frontend_typecheck", (NPM, "--prefix", "frontend", "run", "typecheck"), timeout_seconds=300),
    Check("frontend_tests", (NPM, "--prefix", "frontend", "run", "test", "--", "--run"), timeout_seconds=300),
    Check("frontend_build", (NPM, "--prefix", "frontend", "run", "build"), timeout_seconds=600),
    Check("contract_check", (PYTHON, "-m", "scripts.export_contracts", "--check"), timeout_seconds=300),
)

P09_BROWSER = (
    Check("seed", (PYTHON, "-m", "scripts.seed", "--reset"), timeout_seconds=300,
          env=(("MONGODB_DATABASE", "technologyagent_test_p09_browser"),)),
    Check("full_browser_e2e", (NPM, "--prefix", "frontend", "run", "test:e2e", "--", "--workers=1"),
          timeout_seconds=1200, env=(("MODEL_MODE", "fake"),
             ("MONGODB_DATABASE", "technologyagent_test_p09_browser"),
             ("P04_RESTART_BACKEND", "1"))),
)

P09_LIVE = (
    Check("final_live_scenarios", (PYTHON, "-m", "pytest", "tests/live/test_final_scenarios.py", "-q", "-rs"),
          timeout_seconds=5400,
          env=(("RUN_LIVE_MODEL", "1"), ("MODEL_MODE", "live"),
               ("MONGODB_DATABASE", "technologyagent_test_p09_live")),
          require_pytest_pass=True),
)

P01_OFFLINE = (
    Check("db_init", (PYTHON, "-m", "scripts.init_db"), timeout_seconds=180),
    Check("compatibility", (PYTHON, "-m", "scripts.check_compatibility"), timeout_seconds=300),
    Check(
        "seed",
        (PYTHON, "-m", "scripts.seed", "--reset"),
        timeout_seconds=300,
        env=(("MONGODB_DATABASE", "technologyagent_test_p01_verify"),),
    ),
    Check(
        "unit_tests",
        (PYTHON, "-m", "pytest", "tests/unit", "-q"),
        timeout_seconds=300,
    ),
    Check(
        "integration_tests",
        (PYTHON, "-m", "pytest", "tests/integration", "-q"),
        timeout_seconds=900,
    ),
    Check(
        "frontend_typecheck",
        (NPM, "--prefix", "frontend", "run", "typecheck"),
        timeout_seconds=300,
    ),
    Check(
        "frontend_tests",
        (NPM, "--prefix", "frontend", "run", "test", "--", "--run"),
        timeout_seconds=300,
    ),
    Check(
        "frontend_build",
        (NPM, "--prefix", "frontend", "run", "build"),
        timeout_seconds=600,
    ),
    Check(
        "contract_check",
        (PYTHON, "-m", "scripts.export_contracts", "--check"),
        timeout_seconds=300,
    ),
)

MANIFESTS: dict[str, dict[str, tuple[Check, ...]]] = {
    "P00": {
        "offline": P00_OFFLINE,
        "live": (),
        "browser": (),
    },
    "P01": {
        "offline": P01_OFFLINE,
        "live": (),
        "browser": (),
    },
    "P02": {
        "offline": P02_OFFLINE,
        "live": (),
        "browser": P02_BROWSER,
    },
    "P03": {
        "offline": P03_OFFLINE,
        "live": P03_LIVE,
        "browser": P03_BROWSER,
    },
    "P04": {
        "offline": P04_OFFLINE,
        "live": P04_LIVE,
        "browser": P04_BROWSER,
    },
    "P05": {
        "offline": P05_OFFLINE,
        "live": P05_LIVE,
        "browser": P05_BROWSER,
    },
    "P06": {
        "offline": P06_OFFLINE,
        "live": (),
        "browser": P06_BROWSER,
    },
    "P07": {
        "offline": P07_OFFLINE,
        "live": P07_LIVE,
        "browser": P07_BROWSER,
    },
    "P08": {
        "offline": P08_OFFLINE,
        "live": P08_LIVE,
        "browser": P08_BROWSER,
    },
    "P09": {
        "offline": P09_OFFLINE,
        "live": P09_LIVE,
        "browser": P09_BROWSER,
    },
}

# P00 没有 tests/unit；pytest 对空的 tests/unit 会返回 5，必须判失败。
P00_NOTES = (
    "P00 无 tests/unit，因此 manifest 不含 unit 命令；"
    "P01 起新增的 unit 测试必须成为必跑项。"
)
P01_NOTES = (
    "P01 offline 在 P00 必要检查基础上增加 seed、unit_tests 与 contract_check；"
    "真实模型/订单执行/浏览器 E2E 不在本阶段。"
)
P02_NOTES = (
    "P02 offline 包含 P00/P01 回归、P02 unit/integration、前端解析与构建、契约检查；"
    "browser 模式要求本机已启动 3030/8030，运行 tests/e2e/chat-flow.spec.ts；"
    "P02 不调用真实模型/ERP。"
)
P03_NOTES = (
    "P03 offline 包含 P03 模型/MCP/图/证据测试、P00-P02 回归、前端构建和契约检查；"
    "browser 模式要求本机启动 3030/8030/9030，运行 chat-flow E2E；"
    "live 模式需要显式模型 Key 和 RUN_LIVE_MODEL=1；没有 Key 时不得把 live 标为通过。"
)
P04_NOTES = (
    "P04 offline 包含持久 interrupt、审批事务、幂等/崩溃测试、前端构建和契约检查；"
    "browser 运行 chat-flow 与订单审批流程；live 需要 RUN_LIVE_MODEL=1、真实模型配置、已启动的 live API 和隔离 technologyagent_test_* 数据库。"
)
P05_NOTES = (
    "offline覆盖确定性反例、最多2次修订/3次评审、预算与P04中断恢复；browser覆盖聊天事件刷新恢复及订单页流程。"
    "live需服务以MODEL_MODE=live和technologyagent_test_*隔离库启动，测试固定执行库存Harness及订单写入后只读评审。"
)
P06_NOTES = (
    "offline包含真实Docker镜像构建、隔离/超时/无网络/输出限制及Artifact Mongo/授权测试；"
    "browser执行聊天/订单及持久artifact_ready卡片回归；图表由render_p06_examples.py生成并视觉核对，报告解析事实见evidence/P06.md。"
    "P06无独立真实模型检查；HTML/报告手动浏览器打开状态单独记录。"
)
P07_NOTES = (
    "P07 offline验证升级前真实v1检查点、新run v2 namespace、工具双向权限、父预算、技能hash与用户显式偏好；"
    "browser验证偏好查看/记住/删除；live需显式真实模型与隔离库，执行分析→报告→订单专家并停在同run审批，不批准或提交订单。"
)
P08_NOTES = (
    "P08 offline验证Provider/ERP映射与HTTP传输、23项MCP工具注册、审批提案、收发货事务及固定inbound生命周期；"
    "browser验证通用提案审批展示；live仅在ERP_ENVIRONMENT=test、明确测试端点/操作和授权下执行，模拟器不计真实ERP。"
)
P09_NOTES = (
    "P09离线检查在独立technologyagent_test_p09_verify库执行；browser须真实运行桌面/手机响应式E2E。"
    "live须显式RUN_LIVE_MODEL=1、真实模型配置及technologyagent_test_p09_live隔离库；未配置不得记为通过。"
)


def classify_exit(exit_code: int, argv: tuple[str, ...], output: str = "") -> tuple[str, str]:
    is_pytest = any("pytest" in part for part in argv)
    if exit_code == 5 and is_pytest:
        return "failed", "pytest returned exit 5: no tests collected (never treated as success)"
    if exit_code == 0 and is_pytest:
        summaries = re.findall(r"(?m)^\s*(.*\b(?:passed|failed|skipped|xfailed|xpassed)\b.*?)(?:\s+in\s+\S+)?\s*$", output)
        if summaries:
            last = summaries[-1]
            counts = {name: sum(int(value) for value in re.findall(rf"(\d+)\s+{name}\b", last))
                      for name in ("passed", "failed", "skipped", "xfailed", "xpassed")}
            if counts["skipped"] and not any(counts[name] for name in ("passed", "failed", "xfailed", "xpassed")):
                return "failed", "pytest collected tests but skipped every test (never treated as success)"
    if exit_code == 0:
        return "passed", ""
    return "failed", f"command exited with {exit_code}"


def _tail(text: str, limit: int = 6000) -> str:
    if len(text) <= limit:
        return text
    pytest_error = re.search(
        r"(?mi)^=+\s*(?:ERRORS|FAILURES|short test summary info)\s*=+\s*$",
        text,
    )
    if pytest_error:
        warning_summary = re.search(
            r"(?mi)^=+\s*warnings summary\s*=+\s*$",
            text[pytest_error.start():],
        )
        end = pytest_error.start() + warning_summary.start() if warning_summary else len(text)
        diagnostic = text[pytest_error.start():end].rstrip()
        if len(diagnostic) > limit:
            half = max(1, (limit - 32) // 2)
            diagnostic = diagnostic[:half] + "\n...[pytest diagnostics truncated]...\n" + diagnostic[-half:]
        tail_budget = max(0, limit - len(diagnostic) - 2)
        tail = text[-tail_budget:] if tail_budget else ""
        return diagnostic + ("\n\n" + tail if tail else "")
    return text[-limit:]


def _prepare_pytest_basetemp(
    environment: dict[str, str], cwd: Path, argv: tuple[str, ...] | list[str] = ()
) -> None:
    options = environment.get("PYTEST_ADDOPTS", "") + " " + " ".join(argv)
    match = re.search(r"(?:^|\s)--basetemp(?:=|\s+)(\"[^\"]+\"|'[^']+'|[^\s]+)", options)
    if not match:
        return
    target = Path(match.group(1).strip("\"'"))
    if not target.is_absolute():
        target = cwd / target
    target.parent.mkdir(parents=True, exist_ok=True)


def run_check(check: Check) -> dict[str, object]:
    started = time.perf_counter()
    exit_code: int | None = None
    status = "failed"
    detail = ""
    stdout = ""
    stderr = ""
    cmd = list(check.argv)
    environment = os.environ.copy()
    environment.update(dict(check.env))
    _prepare_pytest_basetemp(environment, check.cwd, cmd)
    try:
        completed = subprocess.run(
            cmd,
            cwd=str(check.cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=check.timeout_seconds,
            env=environment,
        )
        exit_code = completed.returncode
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        status, detail = classify_exit(exit_code, check.argv, stdout + "\n" + stderr)
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", "replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", "replace")
        status = "failed"
        detail = f"timed out after {check.timeout_seconds}s"
    except FileNotFoundError as exc:
        status = "failed"
        detail = f"executable not found: {exc.filename}"
    except Exception as exc:  # noqa: BLE001
        status = "failed"
        detail = f"{type(exc).__name__}: {exc}"

    output = stdout
    if stderr:
        output += "\n[stderr]\n" + stderr
    if check.require_pytest_pass:
        from scripts.live_acceptance import pytest_execution_issues
        issues = pytest_execution_issues(output)
        if issues:
            status = "failed"
            detail = "; ".join(issues)
    return {
        "name": check.name,
        "command": cmd,
        "cwd": str(check.cwd),
        "required": check.required,
        "exit_code": exit_code,
        "status": status,
        "detail": detail,
        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        "output_tail": _tail(output.strip()),
    }


def manifest_as_dict(stage: str, mode: str) -> dict[str, object]:
    checks = MANIFESTS[stage][mode]
    return {
        "stage": stage,
        "mode": mode,
        "checks": [
            {
                "name": check.name,
                "argv": list(check.argv),
                "cwd": str(check.cwd),
                "timeout_seconds": check.timeout_seconds,
                "required": check.required,
                "env": dict(check.env),
            }
            for check in checks
        ],
    }


def _write_report(report: dict[str, object], report_path: Path) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="按阶段运行真实检查并保存报告")
    parser.add_argument("stage", choices=sorted(MANIFESTS.keys()))
    parser.add_argument("--mode", choices=("offline", "live", "browser"), default="offline")
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--list", action="store_true", help="只打印 manifest，不执行")
    args = parser.parse_args(argv)

    if args.list:
        print(json.dumps(manifest_as_dict(args.stage, args.mode), ensure_ascii=False, indent=2))
        return 0

    report_path = args.report or (REPORT_ROOT / f"{args.stage}-{args.mode}.json")
    if not report_path.is_absolute():
        report_path = ROOT / report_path

    checks = MANIFESTS[args.stage][args.mode]
    started_at = datetime.now(timezone.utc)
    started = time.perf_counter()

    if args.stage == "P08" and args.mode == "live":
        from backend.app.config import load_settings
        erp_settings = load_settings()
        if (erp_settings.erp_environment != "test" or not erp_settings.erp_base_url
                or not erp_settings.erp_api_key or not erp_settings.mongodb_database.startswith("technologyagent_test_")
                or not os.environ.get("ERP_TEST_READ_OPERATION")
                or not os.environ.get("ERP_TEST_WRITE_OPERATION")
                or not os.environ.get("ERP_TEST_CORRELATION_ID")
                or os.environ.get("ERP_TEST_WRITE_AUTHORIZED") != "1"
                or not os.environ.get("ERP_TEST_WRITE_PAYLOAD")):
            report = {
                "stage": args.stage, "mode": args.mode, "ok": False, "not_run": True,
                "note": "P08 live not_run: an explicitly scoped test ERP, credentials and isolated test database are required.",
                "started_at": started_at.isoformat(), "finished_at": datetime.now(timezone.utc).isoformat(),
                "duration_ms": 0, "checks": [],
            }
            _write_report(report, report_path)
            print("P08 live: not_run (explicit test ERP environment or isolated database missing)")
            print(f"report: {report_path}")
            return 2
    if args.stage in {"P03", "P04", "P05", "P07", "P09"} and args.mode == "live":
        from backend.app.config import load_settings

        live_settings = load_settings()
        if (
            os.environ.get("RUN_LIVE_MODEL") != "1"
            or not live_settings.model_configured
            or live_settings.model_mode != "live"
            or not live_settings.mongodb_database.startswith("technologyagent_test_")
        ):
            report = {
                "stage": args.stage,
                "mode": args.mode,
                "ok": False,
                "not_run": True,
                "note": f"{args.stage} live requires RUN_LIVE_MODEL=1, MODEL_MODE=live, configured model credentials and an isolated technologyagent_test_* database.",
                "started_at": started_at.isoformat(),
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "duration_ms": 0,
                "checks": [],
            }
            _write_report(report, report_path)
            print(f"{args.stage} live: not_run (explicit live configuration or isolated test database missing)")
            print(f"report: {report_path}")
            return 2

    if not checks:
        report = {
            "stage": args.stage,
            "mode": args.mode,
            "ok": False,
            "not_run": True,
            "note": f"{args.stage} has no {args.mode} checks; no verification was performed.",
            "started_at": started_at.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "duration_ms": 0,
            "checks": [],
        }
        _write_report(report, report_path)
        print(f"{args.stage} {args.mode}: not_run (no checks for this stage/mode)")
        print(f"report: {report_path}")
        return 2

    results: list[dict[str, object]] = []
    for check in checks:
        print(f"==> {check.name}: {' '.join(check.argv)}")
        result = run_check(check)
        results.append(result)
        print(f"    {result['status']} (exit={result['exit_code']}) {result['detail']}")
        if result["status"] != "passed":
            print(result["output_tail"])
        if result["status"] != "passed" and check.required:
            # 继续收集？阶段检查失败即失败，但保留后续命令的实际退出码。
            pass

    passed = all(item["status"] == "passed" for item in results)
    finished_at = datetime.now(timezone.utc)
    report = {
        "stage": args.stage,
        "mode": args.mode,
        "ok": passed,
        "not_run": False,
        "note": P00_NOTES if args.stage == "P00" else P01_NOTES if args.stage == "P01" else P02_NOTES if args.stage == "P02" else P03_NOTES if args.stage == "P03" else P04_NOTES if args.stage == "P04" else P05_NOTES if args.stage == "P05" else P06_NOTES if args.stage == "P06" else P07_NOTES if args.stage == "P07" else P08_NOTES if args.stage == "P08" else P09_NOTES if args.stage == "P09" else "",
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        "checks": results,
    }
    _write_report(report, report_path)
    print(f"{args.stage} {args.mode}: {'PASS' if passed else 'FAIL'}")
    print(f"report: {report_path}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
