# 参与开发

AgentBarrage 目前是 macOS 原型，使用 [MIT 许可证](./LICENSE)，尚未发布正式安装包。提交代码前请先阅读 [架构说明](./ARCHITECTURE.md)和[安全说明](./SECURITY.md)。

## 添加一个智能体

1. 在 `agent_barrage/adapters/` 新增 `normalize(payload)`，只返回 [Event v1](./ARCHITECTURE.md#event-v1) 或 `None`。不要把原始提示词、工具参数、输出、路径和凭证复制进事件。可选 `detail` 只能从许可字段提取短提示，并须证明不会带出命令参数或文件内容。
2. 在 `agent_barrage/emit.py` 注册适配器名；如该工具支持生命周期 Hook，在 `agent_barrage/install.py` 增加可选安装和独立卸载逻辑。
3. 用官方 Hook 文档和真实产品版本核对事件覆盖；给正常完成、请求输入、失败和不支持事件添加测试。普通工具事件须通过 `ProgressGate` 控制频率，重要事件不能被过滤。
4. 在 README 标注适配器覆盖的具体产品形态。CLI、桌面应用、IDE 不能因为品牌名称相同就假设使用相同 Hook。

## 本机验证

```sh
python3 -m unittest discover -s tests -v
python3 bin/agent-barrage
python3 bin/agent-barrage --demo
python3 bin/agent-barrage-send --agent my-agent --kind success --message "测试完成" --project Demo
```

Hook 安装器使用 `--dry-run` 查看将变更的目标路径、命令和事件；卸载时只移除 AgentBarrage 的处理器。安装后还要按智能体自身的规则完成 Hook 信任审查。
