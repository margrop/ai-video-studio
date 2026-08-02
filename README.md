# AI Video Studio

> AI Content Pipeline：Article → Video → Voice → Social

AI Video Studio（AIVS）是一个 provider-neutral 的 AI 内容流水线。它的核心不是把某个视频模型封装成脚本，而是把内容规划、分镜、提示词、配音、字幕、渲染和后续发布拆成可以复用、测试和替换的模块。

当前版本是 Phase 2 foundation：

```text
Markdown / Topic
  → Story Plan
  → Shot List + Prompt Builder
  → SRT subtitles
  → TTS Provider (or offline silent audio)
  → FFmpeg vertical MP4
```

## 现在可以做什么

- `aivs generate "介绍 MCP 是什么"` 一句话生成一个 9:16 MP4；
- `aivs plan` 单独生成版本化 `story-plan-v1`；
- FastAPI 接受任务，文件队列 worker 处理任务；
- 任务具有幂等键、服务端重试预算、worker lease 和崩溃恢复；
- 可以查看任务列表、状态统计、事件流和运行时 Provider 能力；
- `/dashboard` 提供零构建依赖的任务控制台，可创建任务、查看事件和下载产物；
- MiniMax H3 通过 OpenAI-compatible LLM Provider 接入 Story Planner；
- TTS 是独立接口，默认使用离线静音 WAV，配置 TTS 后可以切换到服务端语音接口；
- FFmpeg 负责确定性合成，不依赖某一个视频模型；
- Kling、Veo、Runway、OpenAI 等 Provider 有隔离目录和扩展合同。

没有配置 API Key 时，规划和渲染仍然可以离线运行。这个降级路径用于测试和演示，不代表视频模型或 TTS 已经接通。

## 快速开始

需要 Python 3.12、FFmpeg。建议创建虚拟环境后安装开发依赖：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'

# 完全离线生成一个演示视频
aivs generate "用一分钟介绍 MCP" --no-ai --output artifacts/mcp-intro.mp4

# 从技术文章生成
aivs generate "AI Gateway 的作用" --source examples/tech-blog.md --no-ai \
  --output artifacts/ai-gateway.mp4
```

验证生成文件：

```bash
ffprobe -v error -show_entries format=duration,size \
  -of default=noprint_wrappers=1 artifacts/mcp-intro.mp4
```

## 使用 MiniMax H3

AIVS 不在用户请求中接受 `provider`、`model`、`messages` 或 API Key。Provider 和模型由服务端环境配置决定，符合现有 `margrop-labs` 的 AI Gateway 边界。

```bash
export AIVS_LLM_BASE_URL="http://127.0.0.1:3001/v1"
export AIVS_LLM_API_KEY="your-local-secret"
export AIVS_LLM_MODEL="MiniMax-H3"
aivs generate "介绍 AI 面试工作台" --output artifacts/interview-workbench.mp4
```

如果上游不可用，Story Planner 会返回确定性降级计划，并在 `warnings` 中说明原因；不会伪造“AI 已成功生成”。

## API 与 Worker

终端一：

```bash
uvicorn apps.api.main:app --reload
```

终端二：

```bash
aivs-worker
```

提交任务：

```bash
curl -X POST http://127.0.0.1:8000/v1/jobs \
  -H 'content-type: application/json' \
  -d '{"topic":"介绍 MCP","duration_seconds":60,"use_ai":false}'
```

然后用返回的 `job_id` 查询 `/v1/jobs/{job_id}`，成功后从 `/v1/jobs/{job_id}/artifacts/video.mp4` 下载。

客户端重试时建议发送相同的 `Idempotency-Key`，避免网络超时造成重复任务：

```bash
curl -X POST http://127.0.0.1:8000/v1/jobs \
  -H 'content-type: application/json' \
  -H 'Idempotency-Key: mcp-intro-2026-08-01' \
  -d '{"topic":"介绍 MCP","duration_seconds":60,"use_ai":false}'
```

运维接口：`GET /v1/jobs`、`GET /v1/stats`、`GET /v1/providers` 和
`GET /v1/jobs/{job_id}/events`。

## 项目结构

```text
apps/
├── api/       # FastAPI 任务 API
├── worker/    # 文件队列 worker；Phase 2 可替换 Redis/Celery
├── cli/       # 一句话 CLI
└── web/       # 零构建依赖的 Web 管理后台
packages/
├── contracts/ # Story Plan、Job、API 合同
├── llm/       # provider-neutral LLM 接口
├── planner/   # AI/确定性 Story Planner
├── storyboard/# Prompt Builder
├── providers/ # VideoProvider 与 Registry
├── subtitle/  # SRT
├── tts/       # TTS 接口与实现
├── ffmpeg/    # 确定性视频合成
├── storage/   # 本地任务状态
└── workflow/  # 内容流水线编排
providers/
├── minimax/   # MiniMax H3 / TTS 适配器
├── openai/    # OpenAI-compatible 适配器
├── kling/     # 扩展位置
├── veo/       # 扩展位置
└── runway/    # 扩展位置
```

## 设计原则

1. Provider-neutral：工作流只依赖接口，不依赖供应商 SDK。
2. Deterministic core：合同验证、字幕、存储和 FFmpeg 合成由代码负责。
3. Safe fallback：模型、TTS 或额度不可用时保留可审阅的确定性结果。
4. Secret boundary：密钥只来自服务端环境，不写入任务文件、日志或 URL。
5. Small verifiable slices：每个阶段都可以离线测试、回滚和替换。

这些原则延续了 [`ai-infrastructure-toolkit`](https://github.com/margrop/ai-infrastructure-toolkit) 的证据优先与安全边界，以及 [`margrop-labs`](https://github.com/margrop/margrop-labs) 的 AI Gateway 合同。

## 质量检查

```bash
ruff check .
ruff format --check .
pytest
```

完整质量门：

```bash
./scripts/quality.sh
```

## 路线图

- Phase 1：FastAPI、worker、CLI、H3 planner、TTS 接口和 FFmpeg。
- Phase 2（当前）：可恢复本地任务队列、幂等、重试、事件、Provider 能力和运维 API；接下来是 Dashboard、Redis/Postgres 和用量账本。
- Phase 3：Character Library、Asset Library、真正的视频 Provider、多镜头素材。
- Phase 4：MCP Server、博客/公众号/知乎/B 站等发布 Workflow。

本项目使用 MIT License，详见 [`LICENSE`](LICENSE)。
