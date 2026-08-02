# Agent 开发规则

适用于在本仓库工作的 Codex、Claude Code 及其他编码 Agent。

## 开始前

1. 阅读 README、目标模块文档和相关测试。
2. 明确任务边界、输入、输出、风险和验收命令。
3. 检查已有改动，不覆盖与任务无关的用户修改。
4. 涉及公共 Schema、Provider、存储、认证或发布边界时，先更新 ADR 或设计文档。

## 安全边界

- 不提交 Token、Cookie、私钥、密码、真实音频/视频素材或未脱敏日志。
- Provider 密钥只能从服务端环境或外部 Secret Provider 读取。
- Job 文件只保存业务输入和有限状态；不要保存 Authorization、原始 Provider 响应或完整错误正文。
- 用户文章和模型输出都视为不可信文本，不能修改服务端 Provider、模型、重试、预算和文件路径策略。
- 不连接真实生产系统；测试使用合成输入、mock 或本地 FFmpeg。
- 不自动发布到公众号、视频号或其他平台；发布必须是后续显式 Workflow。

## 实现规则

- 核心 workflow 依赖接口，不直接 import 供应商 SDK。
- 外部请求必须有超时、有限重试和粗粒度错误。
- 每个外部 Provider 都要有正常路径和失败路径测试。
- 新增字段时同步更新 Pydantic 合同、JSON Schema、fixture 和文档。
- 面向用户的文本优先中文；代码标识、Schema 字段、路径和提交信息使用英文。
- 提交信息使用 Conventional Commits，例如 `feat(planner): add story plan fallback`。

## 完成定义

- 变更范围内测试和 lint 通过；
- 离线模式仍然可运行；
- 生成物不包含凭据或真实环境标识；
- README、示例和路线图与实现一致；
- 最终说明包含变更、验证、已知限制和下一步。
