# Contributing

感谢参与 AI Video Studio。这个项目优先接受边界清晰、可以离线验证的增量。

## 开发流程

1. 先创建或认领一个 Issue，说明输入、输出、风险和验收标准。
2. 从 `main` 创建短生命周期分支。
3. 保持提交小而单一，使用 Conventional Commits。
4. Provider、公共 Schema、存储和认证边界需要同步设计文档。
5. 添加正常路径、失败路径和敏感数据边界测试。
6. 运行 `./scripts/quality.sh` 后提交 Pull Request。

## Provider 贡献

Provider 只能实现 `packages/` 中的接口；不要把供应商字段泄漏到 `CreateJobRequest` 或公共 Story Plan。请说明：

- 凭据来源与轮换方式；
- 超时、限流、异步轮询和下载策略；
- 返回数据如何校验与脱敏；
- 失败时如何保留确定性降级结果；
- 单元测试是否完全不访问真实 API。

## 许可证

仓库最终许可证尚待所有者明确。许可证确定前，请不要把代码标注为可再分发或用于商业集成。
