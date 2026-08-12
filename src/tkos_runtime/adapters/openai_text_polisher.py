# src/tkos_runtime/adapters/openai_text_polisher.py
"""OpenAI 兼容接口的 TextPolisher 适配器。

只改写文本流畅性——不改事实、分区或锚点。调用方决定降级策略。
"""
from __future__ import annotations

import os
from typing import Optional


class OpenAITextPolisher:
    """通过 OpenAI 兼容 API 润色文本。

    Args:
        base_url: API base URL（默认从 LLM_BASE_URL 环境变量读取）。
        api_key: API 认证令牌（默认从 LLM_AUTH_TOKEN 环境变量读取）。
        model: 模型名（默认从 LLM_MODEL 环境变量读取）。
        timeout: HTTP 请求超时秒数（默认读 LLM_TIMEOUT 环境变量，缺省 120）。
        max_retries: 最大重试次数（默认 1）。
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: int = 1,
    ):
        self._base_url = base_url or os.environ.get("LLM_BASE_URL", "")
        self._api_key = api_key or os.environ.get("LLM_AUTH_TOKEN", "")
        self._model = model or os.environ.get("LLM_MODEL", "")
        self._timeout = (
            timeout if timeout is not None
            else float(os.environ.get("LLM_TIMEOUT", "120"))
        )
        self._max_retries = max_retries
        if not self._base_url or not self._api_key:
            raise ValueError(
                "OpenAITextPolisher requires LLM_BASE_URL and LLM_AUTH_TOKEN "
                "(or pass them as constructor args)."
            )

    def polish(self, text: str, language: str = "zh-CN") -> str:
        """润色文本流畅性，不改事实、分区或锚点。"""
        from openai import OpenAI

        system_prompt = (
            "你是一个严格的文本润色器。你的任务是改善以下结构化事实摘要的"
            "语言流畅性和连贯性，但你必须遵守以下不可破坏的规则：\n\n"
            "1. 不得增删任何事实。\n"
            "2. 不得改变任何 [member:...] 和 [source:...] 锚点的内容或位置。\n"
            "3. 不得将 [source:graph-candidate-and-dispute] 标记的内容移至 "
            "'当前已确认事实' 标题下，反之亦然。\n"
            "4. 不得新增任何 Pack 之外的实体、数字、日期、因果关系或建议。\n"
            "5. 不得删除或修改确认状态标签（如 [Candidate]、[PreliminarilyConfirmed]）。\n"
            "6. 只能改善语言流畅性、连接词和句子结构。\n"
            "7. 保持 Markdown 格式。# ## > - ` 等标记保持不变。\n"
            "8. 保留所有空行分隔。"
        )

        client = OpenAI(
            api_key=self._api_key,
            base_url=self._base_url,
            timeout=self._timeout,
            max_retries=self._max_retries,
        )
        response = client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"请润色以下 {language} 文本：\n\n{text}"},
            ],
            stream=False,
        )
        return response.choices[0].message.content or ""
