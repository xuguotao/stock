# CLAUDE.md

# 外科手术式改动(Surgical Changes)

**只动该动的,只清理自己造的烂摊子。**

编辑已有代码时:
- 不要顺手"改进"相邻的代码、注释或格式。
- 不要重构没坏的东西。
- 匹配既有风格,哪怕你觉得有更好的写法。
- 发现与当前任务无关的死代码 → **提醒用户,不要擅自删除**。

你的改动产生孤儿时:
- 删除因**你的改动**而变得无用的 import / 变量 / 函数。
- 不要删除**既有的**死代码,除非用户明确要求。

**检验标准:每一行改动都能直接追溯到用户的请求。** 追溯不上的,就别动。

# Python 运行环境

本项目由 `uv` 管理,Python 解释器在 `.venv/bin/python` (3.13.5)。

**所有 Python 执行一律用 `uv run` 前缀**,不要直接 `python` / `python3`:

```bash
# 对
uv run python xxx.py
uv run pytest tests/
uv run pip install something

# 错(会跑到 IDF 的 python 环境)
python xxx.py
python3 -m pytest
```

原因:父 shell 的 `PATH` 里有 ESP-IDF 的路径排在前面,直接调 `python` 会指向 `~/.espressif/python_env/idf5.5_py3.13_env/bin/python`。`uv run` 自动使用项目的 `.venv`,无视 PATH 顺序。

> 注:`uv run` 首次运行或 `pyproject.toml` 依赖变更后会自动同步环境,可能较慢。日常开发可用 `uv run --no-sync python ...` 跳过同步。
