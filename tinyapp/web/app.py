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
from core.reliable import reliable_call
from core.chunker import split_text
from tasks import discover_tasks, get_all_tasks, get_task
from tasks.languages import get_lang_name, get_lang_code, get_lang_options


def create_app():
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.secret_key = "tinyapp-secret-key"
    app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10MB

    pool = LLMPool()
    engine = WorkflowEngine(pool)
    memory = Memory()

    # 服务端聊天会话存储 {session_id: [messages]}
    _chat_sessions: dict[str, list] = {}

    discover_tasks()

    # ── 页面 ──

    @app.route("/")
    def landing():
        return render_template("landing.html")

    @app.route("/app")
    def app_page():
        return render_template("index.html")

    @app.route("/privacy")
    def privacy():
        return render_template("privacy.html")

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

    @app.route("/api/languages")
    def api_languages():
        return jsonify([{"code": code, "name": name} for code, name in get_lang_options()])

    # ── 文件解析 ──

    @app.route("/api/parse-file", methods=["POST"])
    def api_parse_file():
        file = request.files.get("file")
        if not file:
            return jsonify({"error": "未选择文件"}), 400

        filename = (file.filename or "").lower()
        try:
            if filename.endswith(".txt"):
                text = file.read().decode("utf-8")
            elif filename.endswith(".docx"):
                text = _parse_docx(file)
            elif filename.endswith(".pdf"):
                text = _parse_pdf(file)
            else:
                return jsonify({"error": "不支持的文件格式，请上传 .txt/.docx/.pdf 文件"}), 400
        except Exception as e:
            return jsonify({"error": f"文件解析失败: {e}"}), 500

        return jsonify({"text": text, "filename": file.filename, "length": len(text)})

    # ── Workflow 执行（SSE 流式） ──

    @app.route("/api/run", methods=["POST"])
    def api_run():
        data = request.json
        task_name = data.get("task_name", "")
        user_input = data.get("user_input", "")
        fast_mode = data.get("fast_mode", False)

        task = get_task(task_name)
        if not task:
            return jsonify({"error": f"未找到任务: {task_name}"}), 404

        # 判断是否需要分段改写
        original_text = _extract_original_text(user_input)
        need_chunk = (task_name == "改写" and len(original_text) > 4000)

        event_queue = queue.Queue()
        step_timers: dict[int, float] = {}

        def emit_step(step_num, total, step_name, step_desc, status, elapsed=None):
            if status == "start":
                step_timers[step_num] = time.time()
            if status in ("done", "error") and step_num in step_timers and elapsed is None:
                elapsed = round(time.time() - step_timers[step_num], 1)
            event_queue.put({
                "type": "step",
                "step_num": step_num,
                "total": total,
                "step_name": step_name,
                "description": step_desc,
                "status": status,
                "elapsed": elapsed,
            })

        def run_workflow():
            try:
                if need_chunk:
                    _run_chunked_rewrite(user_input, original_text, fast_mode, emit_step, event_queue, pool)
                else:
                    steps = [s.to_dict() for s in task.steps]
                    if fast_mode:
                        steps = steps[:-1]

                    def on_step(step_num, total, step_name, step_desc, status, step_data):
                        emit_step(step_num, total, step_name, step_desc, status)

                    result = engine.run(
                        task_name=task_name,
                        steps=steps,
                        user_input=user_input,
                        on_step=on_step,
                    )

                    # 改写任务：从改写步骤取正文，审校步骤取评分
                    final_output = result.final_output
                    if task_name == "改写" and result.success:
                        rewrite_data = result.step_outputs.get("改写", {})
                        review_data = result.step_outputs.get("审校", {})
                        final_output = {
                            "content": rewrite_data.get("content", ""),
                            "quality_score": review_data.get("quality_score", 0),
                            "issues": review_data.get("issues", []),
                        }

                    event_queue.put({
                        "type": "result",
                        "success": result.success,
                        "error": result.error,
                        "final_output": _safe_serialize(final_output),
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


def _extract_original_text(user_input: str) -> str:
    """从改写任务的 user_input 中提取原文部分。"""
    marker = "\n\n原文：\n"
    idx = user_input.find(marker)
    return user_input[idx + len(marker):] if idx >= 0 else user_input


def _build_rewrite_header(user_input: str) -> str:
    """从改写任务的 user_input 中提取操作类型/语气等头部信息。"""
    marker = "\n\n原文：\n"
    idx = user_input.find(marker)
    return user_input[:idx] if idx >= 0 else ""


def _run_chunked_rewrite(user_input, original_text, fast_mode, emit_step, event_queue, pool):
    """分段改写长文本：逐段改写 → 合并 → 审校。"""
    from tasks.rewrite import RewriteOutput, ReviewOutput

    chunks = split_text(original_text, max_chars=3500)
    total_steps = len(chunks) + (0 if fast_mode else 1)
    header = _build_rewrite_header(user_input)
    executor = pool.get("executor")

    rewrite_system = "你是专业文字编辑。根据用户要求的操作类型对文本进行改写。\n\n操作类型说明：\n- 扩写：补充细节和论述，丰富内容，保持原意\n- 缩写：精简压缩，保留核心要点，去除冗余\n- 改写：换种表达方式重写，可调整语气\n- 纠错：修正语法、拼写、标点、用词错误\n- 续写：基于原文内容和风格继续往下写\n\n必须输出完整的改写后文本。"

    rewritten_parts = []
    prev_tail = ""

    for i, chunk in enumerate(chunks):
        step_num = i + 1
        step_desc = f"改写第 {i+1}/{len(chunks)} 部分"
        emit_step(step_num, total_steps, "改写", step_desc, "start")

        context_hint = f"\n\n前文末尾：{prev_tail}" if prev_tail else ""
        messages = [
            {"role": "system", "content": rewrite_system},
            {"role": "user", "content": f"{header}\n\n原文：\n{chunk}{context_hint}"},
        ]

        try:
            result = reliable_call(llm=executor, messages=messages, output_model=RewriteOutput)
            rewritten_parts.append(result.content)
            prev_tail = result.content[-200:] if len(result.content) > 200 else result.content
            emit_step(step_num, total_steps, "改写", step_desc, "done")
        except Exception as e:
            emit_step(step_num, total_steps, "改写", step_desc, "error")
            raise

    merged = "\n".join(rewritten_parts)

    if fast_mode:
        event_queue.put({
            "type": "result",
            "success": True,
            "error": None,
            "final_output": {"content": merged, "word_count": len(merged), "changes": []},
            "step_outputs": {},
        })
        return

    # 审校步骤
    review_step = total_steps
    emit_step(review_step, total_steps, "审校", "审校评分 [深度思考]", "start")

    reviewer = pool.get("reviewer")
    review_system = "你是资深文字审校专家。审查改写后的文本质量，逐项检查：\n1. 是否准确完成了用户要求的操作\n2. 语句是否通顺自然，逻辑是否连贯\n3. 与原文的关系是否合理\n\n只需给出质量评分和发现的问题，不需要输出完整文本。"

    # 检查合并文本是否超出审校模型上下文窗口
    review_ctx = pool.get_context_window("reviewer")
    review_text, sampled = _build_review_text(merged, rewritten_parts, review_ctx)
    review_content = f"{header}\n\n改写后文本：\n{review_text}"
    if sampled:
        review_content += "\n\n（注：文本较长，以上为采样片段，请据此评估整体质量）"

    review_messages = [
        {"role": "system", "content": review_system},
        {"role": "user", "content": review_content},
    ]

    try:
        review_result = reliable_call(llm=reviewer, messages=review_messages, output_model=ReviewOutput)
        emit_step(review_step, total_steps, "审校", "审校评分 [深度思考]", "done")

        final_output = {
            "content": merged,
            "quality_score": review_result.quality_score,
            "issues": review_result.issues,
        }
        event_queue.put({
            "type": "result",
            "success": True,
            "error": None,
            "final_output": _safe_serialize(final_output),
            "step_outputs": {"审校": _safe_serialize(final_output)},
        })
    except Exception as e:
        emit_step(review_step, total_steps, "审校", "审校评分 [深度思考]", "error")
        # 审校失败时返回合并后的改写结果
        event_queue.put({
            "type": "result",
            "success": True,
            "error": f"审校步骤失败: {e}",
            "final_output": {"content": merged, "quality_score": 0, "issues": [str(e)]},
            "step_outputs": {},
        })


def _build_review_text(merged: str, parts: list[str], max_ctx: int) -> tuple[str, bool]:
    """构建审校文本，超长时采样代表性片段。返回 (文本, 是否采样)。"""
    from core.llm import estimate_tokens

    estimated = estimate_tokens(merged)
    if estimated + 500 < max_ctx:
        return merged, False

    # 采样：首段、末段、中间均匀取 1-2 段
    if len(parts) <= 2:
        return "\n\n".join(parts), True

    samples = [parts[0]]
    mid = len(parts) // 2
    if mid > 0:
        samples.append(parts[mid])
    if len(parts) > 2:
        samples.append(parts[-1])

    return "\n\n...（省略）...\n\n".join(samples), True


def _parse_docx(file_storage):
    from docx import Document
    doc = Document(file_storage)
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


def _parse_pdf(file_storage):
    import fitz
    doc = fitz.open(stream=file_storage.read(), filetype="pdf")
    text = "\n".join(page.get_text() for page in doc)
    doc.close()
    return text


def _safe_serialize(obj):
    if isinstance(obj, dict):
        return {str(k): _safe_serialize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_safe_serialize(item) for item in obj]
    if isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    return str(obj)
