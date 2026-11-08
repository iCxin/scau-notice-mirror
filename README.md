# 华农通知镜像

把华南农业大学三个网站的通知每天自动抓取、归档，并生成一个可全文搜索的静态网站，部署在 GitHub Pages 上。

- 抓取来源
  - `https://www.scau.edu.cn/` —— 首页“通知公告”栏目
  - `https://xxgk.scau.edu.cn/` —— 最新信息公开（全量 150 页）
  - `https://wcce.scau.edu.cn/` —— 水利与土木工程学院通知公告（全量 10 页）
- 每天北京时间 06:00 由 GitHub Actions 自动运行，增量抓取新通知并提交到仓库
- 前端为纯静态页面，零外部依赖，支持关键词搜索、来源/时间筛选、正文高亮、附件下载

## 目录结构

```
.
├── crawler/                 # 抓取程序
│   ├── config.py            # 来源、限速、索引长度等配置
│   ├── http.py              # requests 会话、重试、限速、登录跳转识别
│   ├── parsers.py           # 列表页 / 详情页解析
│   ├── clean.py             # 正文清洗、相对链接改写、附件提取
│   ├── pdf_text.py          # 从 PDF 附件抽取文本
│   ├── store.py             # 数据落盘、去重、索引生成
│   └── run.py               # 主流程（命令行入口）
├── docs/                    # GitHub Pages 根目录
│   ├── index.html
│   ├── assets/              # 样式与前端脚本
│   └── data/
│       ├── index.json       # 搜索索引（前端一次性加载）
│       ├── state.json       # 运行状态（是否完成首次全量）
│       └── items/*.json     # 每篇通知的归档数据
├── .github/workflows/crawl.yml
├── requirements.txt
└── README.md
```

## 本地运行

```bash
pip install -r requirements.txt

# 快速试抓（每个来源只抓 1 页）
python -m crawler.run --limit-pages 1

# 首次全量（信息公开 150 页，可能需要十几分钟）
python -m crawler.run --full

# 之后日常增量（每个来源抓最近 1-2 页）
python -m crawler.run
```

预览网站（必须通过 HTTP 访问，直接双击 HTML 会因浏览器限制读不到数据）：

```bash
python -m http.server 8000 --directory docs
# 打开 http://localhost:8000
```

## 部署到 GitHub

1. 在 GitHub 新建一个仓库（Public 或 Private 均可，Pages 对 Private 仓库需要付费账户）。
2. 推送本项目到仓库的 `main` 分支：

```bash
git init
git add .
git commit -m "init: 华农通知镜像"
git branch -M main
git remote add origin https://github.com/<你的用户名>/<仓库名>.git
git push -u origin main
```

3. 开启 Pages：仓库 **Settings → Pages → Build and deployment**
   - Source 选择 `Deploy from a branch`
   - Branch 选择 `main`，目录选择 `/docs`，保存
   - 稍等片刻，站点地址为 `https://<你的用户名>.github.io/<仓库名>/`

4. 开启 Actions 写权限：**Settings → Actions → General → Workflow permissions**
   - 选择 `Read and write permissions`，保存
   - 否则定时任务抓取后无法自动提交数据

5. 首次抓取：**Actions → 每日抓取通知 → Run workflow**
   - 勾选 `full` 以抓取全部历史通知；不勾选则只抓最近几页
   - 首次全量大约需要十几分钟，之后每天增量只需一两分钟

之后无需人工干预，每天 UTC 22:00（北京时间次日 06:00）自动运行。GitHub 的定时任务可能延迟数分钟到数十分钟，属正常现象。

## 数据说明

- 每篇通知保存标题、发布日期、来源、正文 HTML（已清洗）、纯文本、附件链接和原文地址。
- 信息公开与水利学院的通知正文可公开访问；正文为 PDF 的通知会自动抽取文本参与搜索，但不镜像 PDF 文件本身，附件仍指向原站。
- 搜索索引包含标题与正文前 1500 字；完整正文在打开详情时按需加载。
- 同一篇通知若同时出现在多个来源，会按文章编号去重，优先保留带正文的版本。

## 主站通知全文（可选）

`www.scau.edu.cn` 的通知正文受校内统一身份认证（CAS）保护，匿名访问会被重定向到登录页。因此默认只归档标题与日期，前端标注“需登录”。

程序提供两种合规的补全方式，**不包含任何绕过、破解或伪造登录态的实现**：

1. **同标题公开转载补全**（默认开启）
   校级通知常会被信息公开专栏、财务处、学院网站等公开站点转载。程序会在已抓取的数据中查找标题与日期完全一致、且带正文的条目，自动合并正文并计入搜索。
2. **使用你本人授权的会话**（可选）
   如果你是校内成员，可在本地或 GitHub Actions 中配置环境变量 `SCAU_COOKIE`，使用自己浏览器里的登录 Cookie 抓取你本就有权查看的正文：

   ```bash
   # 本地临时使用
   $env:SCAU_COOKIE = "你的 Cookie 字符串"   # PowerShell
   python -m crawler.run --refresh --only scau
   ```

   GitHub Actions 中配置：**Settings → Secrets and variables → Actions → New repository secret**，名称填 `SCAU_COOKIE`。
   工作流已自动读取该 Secret，配置后无需修改代码。

   注意事项：
   - Cookie 有效期通常只有数小时到数天，失效后需重新获取并更新 Secret，不适合长期无人值守的全自动运行。
   - GitHub Actions 使用境外 IP，可能触发学校登录风控，导致 Cookie 提前失效。
   - 请勿把 Cookie 写入代码或提交到仓库；它属于个人凭据。
   - 若抓取失败，程序会自动降级为“需登录”状态，不会中断其他站点的抓取。

## 自定义

在 `crawler/config.py` 的 `SOURCES` 中新增来源，并实现 `parsers.py` 里对应的列表解析器即可。

常用参数：

```bash
python -m crawler.run --only wcce          # 只抓某个来源
python -m crawler.run --limit-pages 3      # 限制列表页数
python -m crawler.run --refresh            # 已归档条目重新抓取
python -m crawler.run --no-pdf             # 关闭 PDF 文本抽取
python -m crawler.run --workers 6          # 提高详情并发
```

## 注意事项

- 程序已做 0.25 秒请求间隔与并发限制，请勿把并发调得过高，避免对学校服务器造成压力。
- 本仓库为非官方镜像，通知内容以原站发布为准；如原站调整页面结构，列表解析器可能需要同步修改。
- 仓库体积会随归档天数增长。若长期运行，可定期清理较早的 `docs/data/items` 并重新生成索引。
