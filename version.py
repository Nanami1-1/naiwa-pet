# -*- coding: utf-8 -*-
"""版本号与仓库地址，全项目唯一来源。

改版本号只改这里。打包脚本 tools/build_exe.py 也读它，
并用 --version 参数在打包时自动改写。
"""

VERSION = "1.3.5"

# 更新源。必须是公开仓库，否则客户端要带 token（不能放客户端里）
REPO = "Nanami1-1/naiwa-pet"
