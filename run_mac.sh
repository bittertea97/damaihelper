#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if command -v python3.10 >/dev/null 2>&1; then
  PYTHON_BIN="python3.10"
else
  PYTHON_BIN="python3"
fi

if ! command -v chromedriver >/dev/null 2>&1 && [ -z "${CHROMEDRIVER:-}" ]; then
  cat <<'MSG'
未找到 chromedriver。

GUI 仍可启动；如果要运行真实 Selenium 抢票脚本，请先安装 macOS 版 ChromeDriver:
  brew install chromedriver

如果已手动安装，可设置环境变量后再运行:
  export CHROMEDRIVER=/path/to/chromedriver
MSG
fi

if [ ! -d ".venv" ]; then
  "$PYTHON_BIN" -m venv .venv
fi

source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python GUI.py
