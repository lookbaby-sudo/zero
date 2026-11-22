import os
import uuid

from dotenv import load_dotenv
from storage import save_record, init_db, get_history
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from pypinyin import lazy_pinyin, Style
from snownlp import SnowNLP
import llm_sentiment   # GLM-4.7-Flash 大模型情感分析

load_dotenv()                        # 读同目录下的 .env，把里面的值装进环境变量

app = FastAPI()

init_db()

# 允许跨源访问的前端地址，从配置里来，多个用逗号分隔
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,   # ← 不再写死
    allow_credentials=True,          # 带 cookie 的跨源请求必须显式允许
    allow_methods=["GET", "POST"],
)


profile = {
    "heroTitle": "关于我",
    "heroSubtitle": "项目，创意，灵感，心得，我的作品",
    "featuredWork": {
        "kicker": "作品",
        "title": "文字实验室",
        "copy": "拼音和情绪，挖掘中文里的细节",
        "linkLabel": "打开作品",
    },
    "identity": {
        "motto": "已识乾坤大，尤怜草木青",
        "learning": "零到全栈",
    },
}

class AnalyzeRequest(BaseModel):
    text: str


def get_session_id(request: Request, response: Response) -> str:
    """发纸条 / 认纸条：请求带着 session_id 就用它，没带就现发一张新的。"""
    sid = request.cookies.get("session_id")
    if not sid:
        sid = uuid.uuid4().hex                               # 一串随机、不重复的 id
        response.set_cookie(
            "session_id",
            sid,
            httponly=True,                                   # 前端 JS 读不到，少一个被偷的口子
            samesite="lax",
            max_age=60 * 60 * 24 * 30,                       # 记 30 天
        )
    return sid


@app.get("/api/profile")
def get_profile():
    return profile

def score_label(score):
    if score >= 0.6:
        return "偏积极"
    elif score <= 0.4:
        return "偏消极"
    else:
        return "中性"

@app.post("/api/analyze")
def analyze(req: AnalyzeRequest, request: Request, response: Response):
    sid = get_session_id(request, response)   # 先认人：谁在分析
    text = req.text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="文本不能为空")

    pinyin = " ".join(lazy_pinyin(text, style=Style.TONE))

    # 优先用 GLM-4.7-Flash 大模型判断情感（更准确），失败/未配 Key 回退 SnowNLP
    llm_result = llm_sentiment.analyze_with_llm(text)
    if llm_result is not None:
        score, label, reason = llm_result["score"], llm_result["label"], llm_result["reason"]
        engine = "llm"
    else:
        try:
            score = round(SnowNLP(text).sentiments, 2)
        except Exception:
            score = 0.5
        label = score_label(score)
        reason = ""
        engine = "snownlp"

    result = {
        "text": req.text,
        "score": score,
        "label": label,
        "pinyin": pinyin,
        "reason": reason,
        "engine": engine,                        # 结果来源：llm / snownlp
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    save_record(sid, result)                     # 存档时记下是谁的记录；session_id 只走 cookie，不进结果
    return result

@app.get("/api/history")
def history(request: Request, response: Response, limit: int = 10):
    sid = get_session_id(request, response)      # 先认人：只查自己那份
    return get_history(sid, limit)               # 取几条由调用方说，默认 10
