#!/bin/bash
# start_router.sh — macOS 一键启动 Cove 模型路由
# 同时加载多个模型，通过单一端口按 model ID 自动调度

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INI_FILE="$SCRIPT_DIR/models_mac.ini"
PORT=8080

# ── 检查 llama-server ──
if ! command -v llama-server &>/dev/null; then
    echo "❌ llama-server 未安装"
    echo "   安装方式: brew install llama.cpp"
    exit 1
fi

# ── 检查配置文件 ──
if [ ! -f "$INI_FILE" ]; then
    echo "❌ 配置文件不存在: $INI_FILE"
    exit 1
fi

# ── 检查端口占用 ──
if lsof -i :$PORT -sTCP:LISTEN &>/dev/null; then
    echo "⚠️  端口 $PORT 已被占用"
    echo "   占用进程:"
    lsof -i :$PORT -sTCP:LISTEN
    echo ""
    read -p "   是否终止占用进程并继续？[y/N] " confirm
    if [ "$confirm" = "y" ] || [ "$confirm" = "Y" ]; then
        lsof -ti :$PORT -sTCP:LISTEN | xargs kill -9 2>/dev/null
        echo "   已终止"
    else
        echo "   已取消"
        exit 0
    fi
fi

# ── 启动路由 ──
echo "========================================"
echo "  Cove Model Router (macOS)"
echo "========================================"
echo ""
echo "📄 配置文件: $INI_FILE"
echo "🌐 服务地址: http://127.0.0.1:$PORT"
echo "📊 按 Ctrl+C 停止服务"
echo ""

llama-server --models-preset "$INI_FILE" --host 127.0.0.1 --port $PORT --models-max 2
