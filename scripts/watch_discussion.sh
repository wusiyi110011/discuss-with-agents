#!/usr/bin/env bash
set -eu
discussion_script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
discussion_python=${DISCUSSION_PYTHON:-python3}
if ! command -v "$discussion_python" >/dev/null 2>&1; then
  echo "错误：请安装 Python 3.10+，或用 DISCUSSION_PYTHON 指定可执行的解释器：$discussion_python" >&2
  exit 2
fi
exec "$discussion_python" "$discussion_script_dir/watch_discussion.py" "$@"
