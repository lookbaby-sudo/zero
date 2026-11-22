# zero-to-tech · 文字实验室

一个中文文本分析小工具：输入一段话，给出情感倾向评分和全文拼音，并把每次分析的结果存下来，每个人只看得到自己的那一份。

前后端分离，已经部署上线，也可在本地完整跑起来。

## 技术栈

- **前端**：Next.js 15（JavaScript + JSX，`output: "export"` 静态导出）+ React 19 + anime.js 动效
- **后端**：FastAPI + uvicorn
- **分析**：`snownlp`（情感）、`pypinyin`（带声调拼音）；可选接大模型（OpenAI 兼容接口），失败自动回退 SnowNLP
- **存储**：SQLite（单文件 `backend/history.db`，随后端一起走）
- **线上**：nginx 托管静态文件并反向代理 `/api/`

## 项目结构

```
app/                    # 文件夹 = 路由（Next.js App Router）
  layout.jsx            # 全站外壳，统一 import css
  page.jsx              # /          → HomeView
  text-lab/page.jsx     # /text-lab  → TextLabView
components/             # Nav / HomeView / TextLabView / InputCard / ResultCard
                        # AnimatedCardGrid / PageHeading / HistoryModal
css/                    # 8 个样式文件
data/site.js            # 页面文案（数据与界面分离）
backend/
  main.py               # FastAPI 应用：/api/profile、/api/analyze、/api/history
  storage.py            # SQLite 建表、存档、查询
  llm_sentiment.py      # 大模型情感分析（可选），失败回退
  requirements.txt      # Python 依赖
  .env.example          # 后端配置示例
next.config.mjs         # output: "export"（构建产物是纯静态）
.env.example            # 前端配置示例
```

## 本地跑起来

需要 Node.js 18+、Python 3.10+。

**后端**（一个终端）：

```bash
cd backend
python3 -m venv .venv            # 首次才需要
source .venv/bin/activate        # Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env             # 按下面「配置说明」填
fastapi dev                      # http://localhost:8000
```

> Windows 上如果 `fastapi dev` 报 `UnicodeEncodeError`（打横幅时的 emoji 撞上 GBK 控制台），加一行 `$env:PYTHONUTF8="1"` 再启动，或者直接用
> `.\.venv\Scripts\python.exe -m uvicorn main:app --reload --port 8000`。

**前端**（另开一个终端）：

```bash
npm install
cp .env.example .env.local       # 按下面「配置说明」填
npm run dev                      # http://localhost:3000
```

## 部署到服务器

前提：服务器上已装好 Python 3.10+、Node.js 18+、nginx，且 nginx 站点根目录指向本项目的 `out/`、监听 80 端口。

**1. 拉代码**

```bash
cd ~/zero
git pull
```

**2. 前端：装依赖、写配置、构建**

```bash
npm install
# .env.local 里把 NEXT_PUBLIC_API_BASE_URL 留空（走同源 /api/，由 nginx 反代）
npm run build                    # 产物在 out/，由 nginx 提供访问
```

**3. 后端：建环境、装依赖、写配置**

```bash
cd backend
python3 -m venv .venv            # 首次部署才需要
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env             # 按下面「配置说明」填
```

**4. 后端：交给 systemd 托管**

新建 `/etc/systemd/system/zero-backend.service`（仓库里的 [`deploy/zero-backend.service`](deploy/zero-backend.service) 就是这份，可以直接拷）：

```ini
[Unit]
Description=zero-to-tech backend (FastAPI + uvicorn)
After=network.target

[Service]
User=root
WorkingDirectory=/root/zero/backend
ExecStart=/root/zero/backend/.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload          # 让 systemd 读到新文件
systemctl enable --now zero-backend   # 开机自启 + 立刻启动
systemctl status zero-backend --no-pager
```

几处关键：

- `WorkingDirectory` 必须是**绝对路径**，不能省——`history.db` 是相对路径，换个目录启动就会建到别处去。
- `ExecStart` 写 `.venv` 里的完整路径，不需要 `activate`，也不依赖 shell 环境。
- `Restart=always` + `RestartSec=3`：进程一死立刻重拉（实测 `kill -9` 后 3 秒就起来了，PID 会变）。
- `WantedBy=multi-user.target`：开机自启。
- 监听 `127.0.0.1` 而不是 `0.0.0.0`：只有本机能连，外部一律走 nginx，8000 不对公网开放。
- `User=root` 是因为项目放在 `/root/zero` 下（`/root` 权限 700）。按最小权限原则本该用专用账号，那需要先把项目挪到 `/opt` 之类的位置，属于后续优化。

**5. nginx**

```nginx
server {
    listen 80;
    server_name <服务器IP或域名>;

    root /root/zero/out;          # 前端静态产物
    index index.html;

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location / {
        try_files $uri $uri/ $uri.html =404;
    }
}
```

仓库里的 [`deploy/nginx-zero.conf`](deploy/nginx-zero.conf) 就是这份，可以直接拷到 `/etc/nginx/sites-enabled/`。

改完 `nginx -t && systemctl reload nginx`。反代生效后：

- `http://<服务器IP>/api/profile` 能通（**不带 8000**）；
- `http://<服务器IP>:8000/...` 从公网**连不上**（8000 不对公网开放）；
- `http://<服务器IP>/docs` 返回 404（被静态目录兜住，接口文档不外露）。

那四行 `proxy_set_header` 是有用的：转手一次，来源会丢——真实 IP、原域名、原协议（http 还是 https）都得靠请求头带过去，否则后端看到的全是 `127.0.0.1` 和 `http`。`X-` 前缀只是老约定，说明"这不是 HTTP 标准头，是大家约好这么传的"。

**6. 安全组 / 防火墙**

只放行 **22（SSH）** 和 **80（HTTP）**。**8000 不要放行**——它只监听 `127.0.0.1`，本来就只服务同一台机器上的 nginx，公网连不上正是预期结果。以后上 HTTPS 再放 443。

**7. 验证**

1. 浏览器访问 `http://<服务器IP>/`，首页能打开；
2. 进文字实验室，随便分析一句，结果正常返回；
3. 点结果卡右上角「历史记录」，能看到刚才那条；
4. 换一个浏览器（或开无痕窗口）再看，历史应该是**空的**——会话隔离生效。

## 配置说明

配置文件**不进 git**，照着 `.env.example` 自己建一份。

**前端**：开发用 `.env.local`

| 键 | 说明 | 本地 | 线上 |
| --- | --- | --- | --- |
| `NEXT_PUBLIC_API_BASE_URL` | 后端接口地址（构建时烧进静态文件，改了要重新 build） | `http://localhost:8000` | 留空，走同源 `/api/` |

**后端**：`backend/.env`

| 键 | 说明 | 本地 | 线上 |
| --- | --- | --- | --- |
| `ALLOWED_ORIGINS` | 允许跨源访问的前端地址，多个用逗号分隔 | `http://localhost:3000` | 照填站点地址。反代同源后浏览器不再发跨域请求，但这行仍要留着——代码从这里读，缺省会回退到 `http://localhost:3000` |
| `LLM_API_KEY` | 大模型 Key（可选，不填自动回退 SnowNLP） | 可空 | 可空 |
| `LLM_BASE_URL` | OpenAI 兼容接口地址 | 默认阿里云百炼 | 同左 |
| `LLM_MODEL` | 模型名 | `qwen-turbo` | 同左 |

## 日常发布

```bash
cd ~/zero
git pull

npm run build                     # 前端改了才需要
systemctl restart zero-backend    # 后端改了才需要
```

前端是静态文件，nginx 直接读磁盘，不用重启；只有改了 nginx 配置才需要 `nginx -t && systemctl reload nginx`。

## 常用运维命令

```bash
systemctl status zero-backend     # 看状态
systemctl restart zero-backend    # 重启
systemctl stop zero-backend       # 停止

journalctl -u zero-backend -f     # 实时看日志（Ctrl+C 退出）
journalctl -u zero-backend -n 50  # 看最近 50 行

nginx -t                          # 改完 Nginx 配置先验语法
systemctl reload nginx            # 再让它重读
```

## 说明

- **数据**：`backend/history.db` 是本地数据，已在 `.gitignore` 里；换机器、重建目录前记得备份，否则历史记录会丢。
- **会话**：每个浏览器第一次访问时，后端会发一个 `session_id` cookie（HttpOnly、30 天），之后的分析记录都挂在它名下，所以「每个人只看得到自己那份」。清 cookie 就等于换了个新访客。
- **进程托管**：后端由 systemd 管理，开机自启、崩溃自动重启；日志用 `journalctl -u zero-backend` 看。旧的手工 `nohup` 方式已不需要。
- **部署形态**：nginx 同源代理，所以浏览器端没有跨域问题；如果哪天前后端拆到不同域名，才需要重新配 `ALLOWED_ORIGINS` 和 `credentials`。
- **文档**：部署方式、配置项、运维命令一变，这份 README 就跟着改。过期的文档比没有文档更糟——照着旧文档做，只会掉进坑里。
