# web/app.py — Flask 应用（API 路由 + SSE + 聊天）

import json
import queue
import threading
import time
import uuid
from datetime import datetime

from flask import Flask, render_template, request, jsonify, Response, session

from core.llm import LLMPool
from core.memory import Memory
from core.tools import get_definitions, execute as tool_execute
from core.workflow import WorkflowEngine
from tasks import discover_tasks, get_all_tasks, get_task


def create_app():
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.secret_key = "tinyapp-secret-key"

    pool = LLMPool()
    engine = WorkflowEngine(pool)
    memory = Memory()

    # 服务端聊天会话存储 {session_id: [messages]}
    _chat_sessions: dict[str, list] = {}

    discover_tasks()

    # ── 页面 ──

    @app.route("/")
    def index():
        return render_template("index.html")

    # ── API ──

    @app.route("/api/tasks")
    def api_tasks():
        tasks = get_all_tasks()
        result = []
        for name, task in tasks.items():
            info = {"name": name, "description": getattr(task, "description", "")}
            if hasattr(task, "steps") and task.steps:
                info["type"] = "workflow"
                info["steps_count"] = len(task.steps)
                info["step_names"] = [s.description or s.name for s in task.steps]
            else:
                info["type"] = "chat"
            result.append(info)
        return jsonify(result)

    @app.route("/api/status")
    def api_status():
        status = pool.check_all()
        models = {}
        role_labels = {"translator": "翻译模型", "executor": "执行模型", "reviewer": "评分模型"}
        for role, ok in status.items():
            models[role] = {
                "label": role_labels.get(role, role),
                "model": pool._roles.get(role, ""),
                "connected": ok,
            }
        return jsonify(models)

    # ── Workflow 执行（SSE 流式） ──

    @app.route("/api/run", methods=["POST"])
    def api_run():
        data = request.json
        task_name = data.get("task_name", "")
        user_input = data.get("user_input", "")

        task = get_task(task_name)
        if not task:
            return jsonify({"error": f"未找到任务: {task_name}"}), 404

        steps = [s.to_dict() for s in task.steps]

        event_queue = queue.Queue()
        step_timers: dict[int, float] = {}

        def on_step(step_num, total, step_name, step_desc, status, step_data):
            if status == "start":
                step_timers[step_num] = time.time()
            elapsed = None
            if status in ("done", "error") and step_num in step_timers:
                elapsed = round(time.time() - step_timers[step_num], 1)
            event_queue.put({
                "type": "step",
                "step_num": step_num,
                "total": total,
                "step_name": step_name,
                "description": step_desc,
                "status": status,
                "data": _safe_serialize(step_data),
                "elapsed": elapsed,
            })

        def run_workflow():
            try:
                result = engine.run(
                    task_name=task_name,
                    steps=steps,
                    user_input=user_input,
                    on_step=on_step,
                )
                event_queue.put({
                    "type": "result",
                    "success": result.success,
                    "error": result.error,
                    "final_output": _safe_serialize(result.final_output),
                    "step_outputs": _safe_serialize(result.step_outputs),
                })
            except Exception as e:
                event_queue.put({"type": "error", "message": str(e)})
            finally:
                event_queue.put(None)

        thread = threading.Thread(target=run_workflow, daemon=True)
        thread.start()

        def generate():
            while True:
                try:
                    event = event_queue.get(timeout=300)
                except queue.Empty:
                    yield f"data: {json.dumps({'type': 'error', 'message': '执行超时'}, ensure_ascii=False)}\n\n"
                    break
                if event is None:
                    break
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

        return Response(generate(), mimetype="text/event-stream")

    # ── 聊天 ──

    @app.route("/api/chat", methods=["POST"])
    def api_chat():
        data = request.json
        user_message = data.get("message", "")

        if "chat_id" not in session:
            session["chat_id"] = str(uuid.uuid4())

        chat_id = session["chat_id"]
        if chat_id not in _chat_sessions:
            _chat_sessions[chat_id] = [
                {"role": "system", "content": _build_system_prompt(memory)}
            ]

        messages = _chat_sessions[chat_id]
        messages.append({"role": "user", "content": user_message})

        llm = pool.get("executor")
        tools = get_definitions()

        total_start = time.time()
        tool_events = []

        for turn in range(15):
            try:
                response = llm.chat(messages, tools=tools)
            except Exception as e:
                messages.pop()
                return jsonify({"error": f"调用模型失败：{e}"})

            content = response["content"]
            tool_calls = response["tool_calls"]

            if tool_calls:
                assistant_msg = {"role": "assistant", "content": content or "", "tool_calls": tool_calls}
                messages.append(assistant_msg)

                for tc in tool_calls:
                    name = tc["name"]
                    args = json.loads(tc["arguments"])
                    result = tool_execute(name, args)
                    tool_events.append({"name": name, "args": args, "result": _safe_serialize(result)})
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": json.dumps(result, ensure_ascii=False),
                    })
            else:
                messages.append({"role": "assistant", "content": content})
                elapsed = round(time.time() - total_start, 1)

                # 压缩历史
                if len(messages) > 20:
                    system_msg = messages[0]
                    messages[:] = [system_msg] + messages[-16:]

                return jsonify({
                    "reply": content,
                    "elapsed": elapsed,
                    "tools": tool_events,
                })

        return jsonify({"reply": "抱歉，尝试了很多步还是没能完成任务。请换个方式描述你的需求。", "tools": tool_events})

    @app.route("/api/chat/reset", methods=["POST"])
    def api_chat_reset():
        chat_id = session.pop("chat_id", None)
        if chat_id and chat_id in _chat_sessions:
            del _chat_sessions[chat_id]
        return jsonify({"ok": True})

    return app


def _build_system_prompt(memory: Memory) -> str:
    weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    now = datetime.now()
    prompt = f"""你是一个有用的 AI 助手，运行在本地边缘模型上。

## 身份
- 角色：AI 助手，擅长回答问题、文件操作、信息管理

## 核心约束
- 回答简洁，一般不超过 3 句话
- 不确定的事情直接说不确定
- 使用工具时确保参数正确

## 当前环境
- 时间：{now.strftime('%Y年%m月%d日')} {weekdays[now.weekday()]} {now.strftime('%H:%M')}

{memory.get_context()}"""
    return prompt


def _safe_serialize(obj):
    if isinstance(obj, dict):
        return {str(k): _safe_serialize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_safe_serialize(item) for item in obj]
    if isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    return str(obj)
