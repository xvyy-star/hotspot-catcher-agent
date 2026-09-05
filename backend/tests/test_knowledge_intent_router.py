from app.services.knowledge_intent_router import KnowledgeIntentRouter


def test_smalltalk_should_not_retrieve():
    for text in ["你好", "吃饭了吗", "你到底是谁", "你叫什么", "谢谢"]:
        routed = KnowledgeIntentRouter.route(text)
        assert routed.route == "DIRECT_REPLY"
        assert routed.answer


def test_wrapped_latest_question_should_be_extracted():
    routed = KnowledgeIntentRouter.route(
        "最近对话：\n用户：你好\n\n用户新问题：你到底是谁"
    )
    assert routed.route == "DIRECT_REPLY"
    assert routed.intent == "IDENTITY"
    assert routed.latest_question == "你到底是谁"


def test_knowledge_query_should_retrieve():
    for text in [
        "总结 2026-07-06 早报里的 AI Agent 趋势",
        "分析这两篇历史早报的热点风险",
        "查询知识库里 OpenAI Agent 相关资料",
    ]:
        routed = KnowledgeIntentRouter.route(text)
        assert routed.route == "RAG_QUERY"
