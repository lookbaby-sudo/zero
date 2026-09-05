# backend/llm_sentiment.py
"""大模型情感分析模块（平台无关，默认接阿里云百炼 Qwen-Turbo，免费额度）。

- 默认模型：qwen-turbo（阿里云百炼，每月 100 万 Token 免费，注册送 7000 万）
- 接口：OpenAI 兼容，因此也支持智谱 GLM、硅基流动、DeepSeek 等，只需改 .env
- 鉴权：Authorization: Bearer <LLM_API_KEY>
- Key 从环境变量 LLM_API_KEY 读取，也支持 backend/.env 文件（python-dotenv）
- 任何失败（没配 Key / 网络异常 / 非 200 / 返回格式不合法）都返回 None，
  由调用方（main.py）回退到 SnowNLP，保证接口不宕机。
"""
import json
import logging
import os
import re
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

logger = logging.getLogger("llm_sentiment")

# 加载 backend/.env（若存在）；已存在的环境变量不会被覆盖
load_dotenv(Path(__file__).resolve().parent / ".env")

LLM_API_KEY = os.getenv("LLM_API_KEY", "").strip()
# 默认走阿里云百炼兼容模式；留这个变量方便切换其他 OpenAI 兼容平台
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1").rstrip("/")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen-turbo")

ALLOWED_LABELS = {"偏积极", "中性", "偏消极"}

SYSTEM_PROMPT = """你是中文情感分析专家。用户会给你一段中文文本，请结合语气、程度副词、反语/讽刺、疑问、文化语境等判断作者的真实情感倾向，然后只输出一个 JSON 对象，不要输出任何其他文字、解释或代码块标记。

JSON 格式（严格）：
{"score": 0到1之间的小数, "label": "偏积极"或"中性"或"偏消极", "reason": "不超过30字的中文理由"}

评分标准：0 表示非常消极，0.5 表示完全中性，1 表示非常积极。label 必须与 score 保持一致：score>=0.6 时 label 为"偏积极"，score<=0.4 时 label 为"偏消极"，否则为"中性"。

示例：
文本：这家店的服务态度特别好，下次还来！
输出：{"score": 0.93, "label": "偏积极", "reason": "明确表扬服务并表达复购意愿"}

文本：这破网又卡了，一下午什么都干不了。
输出：{"score": 0.12, "label": "偏消极", "reason": "抱怨网络卡顿影响工作"}

文本：今天下雨，明天出门记得带伞。
输出：{"score": 0.5, "label": "中性", "reason": "客观提醒，无明显情绪色彩"}"""


def _parse_llm_json(content: str):
    """从模型输出中提取 JSON 对象，容忍 markdown 代码块和多余文字；失败返回 None。"""
    if not content:
        return None
    text = content.strip()
    # 去掉 ```json ... ``` 代码块
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


def _validate(data):
    """校验并归一化模型返回的情感结果；任何一项不合法都返回 None。"""
    if not isinstance(data, dict):
        return None
    try:
        score = float(data.get("score"))
    except (TypeError, ValueError):
        return None
    if not (0.0 <= score <= 1.0):
        return None
    label = data.get("label", "")
    if label not in ALLOWED_LABELS:
        # label 不合法时按分数重新映射，与 score_label 保持同一套口径
        label = "偏积极" if score >= 0.6 else ("偏消极" if score <= 0.4 else "中性")
    reason = str(data.get("reason", "")).strip()[:60]
    return {"score": round(score, 2), "label": label, "reason": reason}


def analyze_with_llm(text, timeout: float = 15.0):
    """调用大模型分析中文文本情感。

    返回 {"score": float, "label": str, "reason": str}；任何失败返回 None。
    """
    if not LLM_API_KEY:
        logger.warning("未配置 LLM_API_KEY，跳过 LLM 情感分析（回退 SnowNLP）")
        return None

    # 情感判断不需要全文，截断到 2000 字足够，避免超长文本拖慢请求
    excerpt = text[:2000]
    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"请分析下面这段文本的情感：\n\"\"\"\n{excerpt}\n\"\"\""},
        ],
        "temperature": 0.2,  # 低温度，让评分更稳定
        "max_tokens": 200,   # 只回一个 JSON，200 足够
    }
    headers = {
        "Authorization": f"Bearer {LLM_API_KEY}",
        "Content-Type": "application/json",
    }

    content = None
    # 免费模型高峰期常返回 429（访问量过大），这里重试一次，降低回退概率
    for attempt in range(2):
        try:
            resp = requests.post(
                f"{LLM_BASE_URL}/chat/completions",
                headers=headers,
                json=payload,
                timeout=timeout,
            )
            if resp.status_code == 200:
                content = resp.json()["choices"][0]["message"]["content"]
                break
            if resp.status_code == 429 and attempt == 0:
                logger.warning("LLM 429 过载，2 秒后重试一次...")
                time.sleep(2)
                continue
            logger.warning("LLM 返回异常状态码 %s: %s", resp.status_code, resp.text[:200])
            return None
        except Exception as exc:  # 网络、超时、解析异常一律回退
            logger.warning("LLM 调用失败，回退 SnowNLP: %s", exc)
            return None

    if content is None:
        return None
    return _validate(_parse_llm_json(content))
