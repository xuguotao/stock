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

直接使用系统 zsh,Python 解释器为 conda base(`/opt/anaconda3/bin/python`)。`.zshrc` 已将 `/opt/anaconda3/bin` 加入 PATH,`python` / `python3` 默认即指向 conda base(已含项目依赖,不使用项目 `.venv` / `uv run`)。

```bash
# 对
python xxx.py
pytest tests/

# 若 python 误指向其他环境(如 ESP-IDF),用绝对路径兜底
/opt/anaconda3/bin/python xxx.py
```
