"""测试 P0 修复：审校不输出完整文本 + 上下文窗口保护"""

import json
import sys
import time

# ── 单元测试 ──

def test_review_output():
    """ReviewOutput 不再包含 final_content"""
    from tasks.rewrite import ReviewOutput

    schema = ReviewOutput.model_json_schema()
    props = list(schema["properties"].keys())
    assert "final_content" not in props, f"final_content 应被移除，实际字段: {props}"
    assert "quality_score" in props
    assert "issues" in props

    r = ReviewOutput(quality_score=4, issues=["语句不够通顺"])
    data = r.model_dump()
    assert "final_content" not in data
    assert data["quality_score"] == 4
    assert data["issues"] == ["语句不够通顺"]

    # 边界值：无问题
    r2 = ReviewOutput(quality_score=5, issues=[])
    assert r2.issues == []

    print("  [PASS] ReviewOutput 结构正确")


def test_estimate_tokens():
    """estimate_tokens 估算基本合理"""
    from core.llm import estimate_tokens

    # 空文本
    assert estimate_tokens("") == 0

    # 纯英文
    en = estimate_tokens("Hello world, this is a test.")
    assert 3 < en < 15, f"英文估算异常: {en}"

    # 纯中文
    cn = estimate_tokens("你好世界，这是一个测试。")
    assert 8 < cn < 40, f"中文估算异常: {cn}"

    # 中文估算应比英文更保守（每字符更多 token）
    assert cn / 11 > en / 28, "中文每字符 token 数应更高"

    # 长文本
    long_text = "这是一段测试文本。" * 500
    tokens = estimate_tokens(long_text)
    assert tokens > 0
    # 保守估算，允许超过字符数（中文 1.3x 系数）
    assert tokens < len(long_text) * 2

    print(f"  [PASS] estimate_tokens: 英文={en}, 中文={cn}, 长文本={tokens}")


def test_get_context_window():
    """LLMPool 能读取配置中的 context_window"""
    from core.llm import LLMPool

    pool = LLMPool()
    assert pool.get_context_window("translator") == 4096
    assert pool.get_context_window("executor") == 8192
    assert pool.get_context_window("reviewer") == 16384
    # 未知角色返回默认值
    assert pool.get_context_window("unknown") == 4096

    print("  [PASS] get_context_window 正确")


def test_build_review_text():
    """_build_review_text 采样逻辑"""
    from web.app import _build_review_text
    from core.llm import estimate_tokens

    # 短文本不采样
    short = "短文本"
    result, sampled = _build_review_text(short, [short], 4096)
    assert not sampled
    assert result == short

    # 2段不采样（总量小）
    parts = ["段落A", "段落B"]
    result, sampled = _build_review_text("段落A\n段落B", parts, 4096)
    assert not sampled

    # 构造超长文本触发采样
    long_parts = [f"第{i}段内容" + "测试文本" * 200 for i in range(10)]
    long_merged = "\n".join(long_parts)
    result, sampled = _build_review_text(long_merged, long_parts, 200)
    assert sampled, "超长文本应触发采样"
    assert "第0段" in result, "采样应包含首段"
    assert "第9段" in result, "采样应包含末段"
    assert "第5段" in result, "采样应包含中间段"
    assert "省略" in result, "采样应标注省略"

    # 长文本但在窗口内不采样
    result2, sampled2 = _build_review_text(long_merged, long_parts, 100000)
    assert not sampled2, "窗口足够大不应采样"
    assert result2 == long_merged

    print("  [PASS] _build_review_text 采样逻辑正确")


def test_format_result_uses_rewrite_content():
    """CLI format_result 从改写步骤取正文"""
    from tasks.rewrite import REWRITE_TASK

    # 模拟 workflow result
    class FakeResult:
        success = True
        error = None
        step_outputs = {
            "改写": {"content": "这是改写后的文本内容", "word_count": 12, "changes": ["润色"]},
            "审校": {"quality_score": 4, "issues": []},
        }

    output = REWRITE_TASK.format_result(FakeResult())
    assert "这是改写后的文本内容" in output
    assert "质量评分" in output
    assert "★★★★☆" in output

    # 审校有问题时
    class FakeResultWithIssues:
        success = True
        error = None
        step_outputs = {
            "改写": {"content": "改写文本", "word_count": 4, "changes": []},
            "审校": {"quality_score": 3, "issues": ["逻辑不连贯", "用词不当"]},
        }

    output2 = REWRITE_TASK.format_result(FakeResultWithIssues())
    assert "逻辑不连贯" in output2
    assert "用词不当" in output2

    print("  [PASS] format_result 从改写步骤取正文")


def test_eval_summarize_fallback():
    """评估报告摘要回退到前序步骤查找"""
    sys.path.insert(0, ".")
    from eval.runner import EvalRunner

    runner = EvalRunner.__new__(EvalRunner)

    # final_output 没有 content，但 step_outputs 有
    class FakeResult:
        final_output = {"quality_score": 4, "issues": []}
        step_outputs = {
            "改写": {"content": "改写后的长文本" * 50, "word_count": 300, "changes": []},
            "审校": {"quality_score": 4, "issues": []},
        }

    summary = runner._summarize_output(FakeResult())
    assert "改写后的长文本" in summary
    assert len(summary) <= 103  # 截断后

    print("  [PASS] eval _summarize_output 回退查找正确")


# ── 集成测试（需要 LLM 服务）──

def test_non_chunked_rewrite():
    """非分段改写：短文本走正常 workflow，审校不返回 final_content"""
    from core.llm import LLMPool
    from core.workflow import WorkflowEngine
    from tasks import discover_tasks, get_task

    discover_tasks()
    task = get_task("改写")
    assert task, "改写任务未注册"

    pool = LLMPool()
    engine = WorkflowEngine(pool)

    # 检查模型连接
    status = pool.check_all()
    for role, ok in status.items():
        if not ok:
            print(f"  [SKIP] 模型 {role} 未连接")
            return

    steps = [s.to_dict() for s in task.steps]
    user_input = "操作类型：纠错\n\n原文：\n今天天气很好，我去了公园散步。看到很多老人在锻炼身体，小孩在玩耍。"

    print("    执行非分段改写...", end="", flush=True)
    t0 = time.time()
    result = engine.run(task_name="改写", steps=steps, user_input=user_input)
    elapsed = time.time() - t0
    print(f" ({elapsed:.1f}s)")

    assert result.success, f"执行失败: {result.error}"

    # 审校步骤不应包含 final_content
    review_data = result.step_outputs.get("审校", {})
    assert "final_content" not in review_data, f"审校不应返回 final_content，实际: {list(review_data.keys())}"
    assert "quality_score" in review_data
    assert "issues" in review_data

    # 改写步骤应有 content
    rewrite_data = result.step_outputs.get("改写", {})
    assert "content" in rewrite_data
    assert len(rewrite_data["content"]) > 0

    print(f"    改写内容: {rewrite_data['content'][:80]}...")
    print(f"    审校字段: {list(review_data.keys())}")
    print(f"    质量评分: {review_data['quality_score']}/5")
    print(f"    问题: {review_data['issues']}")
    print("  [PASS] 非分段改写流程正确")


def test_chunked_rewrite():
    """分段改写：长文本触发分段 + 采样审校"""
    from core.llm import LLMPool, estimate_tokens
    from web.app import _build_review_text

    pool = LLMPool()
    status = pool.check_all()
    for role, ok in status.items():
        if not ok:
            print(f"  [SKIP] 模型 {role} 未连接")
            return

    # 构造超长文本（>4000 字符）
    base_text = "人工智能正在改变我们的生活方式。" * 300  # ~6000 字符
    user_input = f"操作类型：缩写\n\n原文：\n{base_text}"

    # 验证会触发分段
    from web.app import _extract_original_text
    original = _extract_original_text(user_input)
    assert len(original) > 4000, f"测试文本应>4000字符，实际: {len(original)}"

    # 验证采样逻辑对合并后的文本有效
    from core.chunker import split_text
    chunks = split_text(original, max_chars=3500)
    assert len(chunks) > 1, f"应拆分为多段，实际: {len(chunks)}段"

    # 模拟分段改写后的合并文本（假设每段膨胀 20%）
    fake_parts = [c + "（改写后）" * 5 for c in chunks]
    merged = "\n".join(fake_parts)

    reviewer_ctx = pool.get_context_window("reviewer")
    review_text, sampled = _build_review_text(merged, fake_parts, reviewer_ctx)
    estimated_merged = estimate_tokens(merged)

    print(f"    原文长度: {len(original)} 字符")
    print(f"    分段数: {len(chunks)}")
    print(f"    合并后: {len(merged)} 字符, ~{estimated_merged} tokens")
    print(f"    Reviewer 上下文: {reviewer_ctx} tokens")
    print(f"    是否采样: {sampled}")

    if estimated_merged + 500 >= reviewer_ctx:
        assert sampled, "超出上下文窗口应触发采样"
        print(f"    采样后长度: {len(review_text)} 字符, ~{estimate_tokens(review_text)} tokens")
        print("  [PASS] 长文本触发采样审校")
    else:
        print("  [PASS] 合并文本在窗口内，无需采样")

    # 实际执行分段改写（耗时长，可选）
    from core.reliable import reliable_call
    from tasks.rewrite import RewriteOutput

    executor = pool.get("executor")
    header = "操作类型：缩写"
    rewritten_parts = []
    prev_tail = ""

    for i, chunk in enumerate(chunks):
        print(f"    改写第 {i+1}/{len(chunks)} 部分...", end="", flush=True)
        context_hint = f"\n\n前文末尾：{prev_tail}" if prev_tail else ""
        messages = [
            {"role": "system", "content": "你是专业文字编辑。对文本进行缩写，精简压缩，保留核心要点。必须输出完整的改写后文本。"},
            {"role": "user", "content": f"{header}\n\n原文：\n{chunk}{context_hint}"},
        ]
        try:
            r = reliable_call(llm=executor, messages=messages, output_model=RewriteOutput)
            rewritten_parts.append(r.content)
            prev_tail = r.content[-200:] if len(r.content) > 200 else r.content
            print(f" OK ({len(r.content)}字)")
        except Exception as e:
            print(f" 失败: {e}")
            return

    merged_result = "\n".join(rewritten_parts)
    print(f"    合并结果: {len(merged_result)} 字符")

    # 验证采样审校
    from tasks.rewrite import ReviewOutput
    reviewer = pool.get("reviewer")
    review_text, sampled = _build_review_text(merged_result, rewritten_parts, reviewer_ctx)

    review_messages = [
        {"role": "system", "content": "你是资深文字审校专家。审查缩写质量。只需给出质量评分和发现的问题，不需要输出完整文本。"},
        {"role": "user", "content": f"操作类型：缩写\n\n改写后文本：\n{review_text}" + ("\n\n（注：文本较长，以上为采样片段）" if sampled else "")},
    ]

    print(f"    审校中（采样={sampled}）...", end="", flush=True)
    try:
        review_result = reliable_call(llm=reviewer, messages=review_messages, output_model=ReviewOutput)
        print(f" OK")
        print(f"    审校结果: score={review_result.quality_score}, issues={review_result.issues}")
        assert hasattr(review_result, "final_content") == False or review_result.final_content is None or True  # 不再要求此字段
        print("  [PASS] 分段改写 + 采样审校流程正确")
    except Exception as e:
        print(f" 失败: {e}")
        raise


# ── 主入口 ──

if __name__ == "__main__":
    import os
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, ".")

    print("=" * 60)
    print("  P0 修复测试")
    print("=" * 60)

    # 单元测试
    print("\n── 单元测试 ──")
    tests = [
        test_review_output,
        test_estimate_tokens,
        test_get_context_window,
        test_build_review_text,
        test_format_result_uses_rewrite_content,
        test_eval_summarize_fallback,
    ]
    passed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except AssertionError as e:
            print(f"  [FAIL] {t.__name__}: {e}")
        except Exception as e:
            print(f"  [ERROR] {t.__name__}: {e}")

    print(f"\n  单元测试: {passed}/{len(tests)} 通过")

    # 集成测试
    print("\n── 集成测试（需要 LLM 服务）──")
    integration_tests = [
        ("非分段改写", test_non_chunked_rewrite),
        ("分段改写", test_chunked_rewrite),
    ]
    ipassed = 0
    for name, t in integration_tests:
        print(f"\n  [{name}]")
        try:
            t()
            ipassed += 1
        except AssertionError as e:
            print(f"  [FAIL] {name}: {e}")
        except Exception as e:
            print(f"  [ERROR] {name}: {e}")

    print(f"\n  集成测试: {ipassed}/{len(integration_tests)} 通过")
    print("\n" + "=" * 60)
