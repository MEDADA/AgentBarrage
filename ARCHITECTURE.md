# 架构与开源边界

## 目标

一个独立的屏幕弹幕程序同时接收多个智能体事件。每个智能体只负责把自己的生命周期事件转换为统一格式；显示层不认识各家的原始 Hook 字段。新智能体可以新增适配器，或直接调用 `agent-barrage-send`，无需修改现有适配器。

```text
Codex Hook ──────> codex adapter ───┐
Claude Code Hook -> claude adapter ──┼─> Event v1 -> local spool -> overlay
CodeBuddy Hook ──> codebuddy adapter ─┤
任意本机工具 ────> send CLI ─────────┘
本机自动化 ──────> token HTTP bridge ─┘
```

## 模块职责

| 模块 | 职责 | 依赖 |
| --- | --- | --- |
| `agent_barrage/core/events.py` | Event v1 字段、长度和来源校验 | Python 标准库 |
| `agent_barrage/core/spool.py` | 本机事件投递、短期缓存与过期清理 | Python 标准库 |
| `agent_barrage/core/history.py` | 最近 200 条弹幕的内存历史、隐私清理 | Python 标准库 |
| `agent_barrage/core/traffic.py` | 重复事件合并、普通事件限流及批次优先级 | Python 标准库 |
| `agent_barrage/adapters/` | 各智能体 Hook 输入到 Event v1 的转换；只允许安全摘要出站 | core |
| `agent_barrage/emit.py` | Hook 统一入口，读取 stdin JSON，选择适配器 | adapters + core |
| `agent_barrage/send.py` | 第三方工具显式发送 Event v1 | core |
| `agent_barrage/install.py` | 对每个工具单独合并/卸载 Hook 配置 | Python 标准库 |
| `agent_barrage/display/macos.py` | macOS 原生悬浮层、菜单栏入口、接入/历史/设置窗口 | AppKit + core |
| `agent_barrage/display/icons.py` | 优先读取本机工具图标（Codex 专用图标），为缺失来源绘制字母标识 | AppKit |
| `agent_barrage/display/sample_events.py` | 仅 `--demo` 使用的假数据 | Python 标准库 |
| `agent_barrage/core/settings.py` | 用户目录设置与旧演示设置迁移 | Python 标准库 |
| `agent_barrage/core/sources.py` | 自定义来源登记、显示名称与安全存储 | Python 标准库 |
| `agent_barrage/bridge.py` | 可选的本机 HTTP 接口，密钥校验后复用 Event v1 | Python 标准库 |

## Event v1

`version`, `agent`, `event`, `kind`, `message`, `project`, `session_id`, `turn_id`, `occurred_at`，以及可选的 `detail` 和 `open_url`。`kind` 为 `working`、`success`、`attention` 或 `error`。`agent` 是小写短标识。`detail` 由适配器从许可字段提取，最长 48 字；仅在用户选择“部分详情”时显示。`open_url` 仅接受不含账号密码的 HTTP(S) 地址，用户从历史记录主动打开。显示层可用 `agent + project` 区分并行任务。

协议默认只发送事件类别、短句和项目名。不得将原始提问、思考、命令全文、工具输入/输出、完整路径或凭证塞进事件。`detail` 当前只允许少量程序名和文件 basename；`project` 是工作目录最后一级名称。启用隐私模式后显示层会进一步隐藏来源和内容。显示层的 `ProgressGate` 默认压缩普通工具事件，重要事件不压缩。

## 本机传输

生产者将单个 JSON 事件原子写入 `/tmp/agentbarrage-<uid>/`，目录权限为 `0700`。显示层轮询、校验并消费，超过 45 秒的事件丢弃。文件传输不要求智能体 Hook 拥有网络或 Unix socket 权限；弹幕程序短暂退出时事件可等待其重新启动。未来可加其他传输实现，但不能改变 Event v1 语义。

自定义来源登记在用户目录，独立于内置适配器。可选 HTTP 接口仅监听 loopback，使用 0600 密钥文件和 Bearer 校验；默认关闭，仅接受已登记来源。它是另一个输入边界，不让远程网页直接读取桌面内容或隐式发送事件。

自定义图标仅存储在用户本机，事件协议不传输图像或路径。内置工具图标从已安装应用读取；无法读取时显示本地绘制的字母标识。第三方商标图片不随开源源码打包。

## 开源发布要求

1. 安装器必须按工具选择、保留原配置、可幂等重装及独立卸载；首次改动用户配置前展示要写入的路径和事件清单。
2. Hook 无论接收器是否运行都应快速退出、绝不批准/拒绝/修改智能体操作。Codex、Claude Code、CodeBuddy 的 Hook 信任机制应由各自产品完成。
3. 隐私模式、屏幕共享行为、多显示器、全屏窗口、无障碍与减少动态效果需持续实机验证；未验证的产品覆盖不宣称已支持。
4. macOS `.app` 已可从源码构建并启动，目前只供本机试用；GitHub 源码开源不依赖应用签名或公证。退出/卸载方式见 README。
5. MIT 许可证、贡献指南和安全报告说明已加入；公开仓库前需配置私密漏洞报告渠道，并加入针对每个工具当前版本的兼容性测试。

## 已知限制

- 目前三个适配器已用模拟 Hook 输入验证共用协议；真实 Hook 在各产品中的触发时机和桌面/IDE 覆盖还需实机验收。
- CodeBuddy 官方 Hook 文档针对 CodeBuddy Code；不能据此断言所有 CodeBuddy 客户端均支持相同接口。
- 当前显示层为 macOS AppKit，Windows/Linux 应分别实现显示层并复用 core 与 adapters。

## 官方接口资料

- [Codex Hooks](https://learn.chatgpt.com/docs/hooks)
- [Claude Code Hooks](https://code.claude.com/docs/en/hooks)
- [CodeBuddy Code Hooks](https://www.codebuddy.ai/docs/cli/hooks)
