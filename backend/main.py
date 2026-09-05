from storage import save_record,init_db, get_history
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from pypinyin import lazy_pinyin, Style
from snownlp import SnowNLP
import llm_sentiment   # GLM-4.7-Flash 大模型情感分析

app = FastAPI()

init_db()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["GET", "POST"],
)


profile = {
    "heroTitle": "关于我",  # → 临时加的标记，验证完删掉
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
def analyze(req: AnalyzeRequest):
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
    save_record(result)                          # ← 存档到文件
    return result

@app.get("/api/history")
def history():
    return get_history(10)




