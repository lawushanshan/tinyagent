# gui.py — TinyApp GUI 启动入口
#
# 双击此文件启动 Web GUI，自动打开浏览器。

import sys
import os
import webbrowser
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from web.app import create_app


def main():
    app = create_app()
    port = 5001

    print()
    print("=" * 48)
    print("    TinyApp — 本地 LLM Workflow 平台")
    print("=" * 48)
    print()
    print(f"  浏览器将自动打开: http://localhost:{port}")
    print(f"  如未打开，请手动访问上述地址")
    print(f"  按 Ctrl+C 退出")
    print()

    threading.Timer(1.5, lambda: webbrowser.open(f"http://localhost:{port}")).start()
    app.run(host="0.0.0.0", port=port, debug=False)


if __name__ == "__main__":
    main()
