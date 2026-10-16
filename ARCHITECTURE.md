# 架构与开源边界

## 目标

一个独立的屏幕弹幕程序同时接收多个智能体事件。每个智能体只负责把自己的生命周期事件转换为统一格式；显示层不认识各家的原始 Hook 字段。新智能体可以新增适配器，或直接调用 `agent-marquee-send`，无需修改现有适配器。

```text
Codex Hook ──────> codex adapter ───┐
Claude Code Hook -> claude adapter ──┤
CodeBuddy Hook ──> codebuddy adapter ─┼─> Event v1/v2 -> local spool -> overlay
任意本机工具 ────> send CLI ─────────┤                    └─> ingestion -> task list
本机自动化 ──────> token HTTP bridge ─┤
微信可见通知 ────> optional AX adapter ─┘ (只作通知)
```

## 模块职责

| 模块 | 职责 | 依赖 |
| --- | --- | --- |
| `agent_marquee/core/events.py` | Event v1 字段、长度和来源校验 | Python 标准库 |
| `agent_marquee/core/event_v2.py` | Event v2 校验、旧事件转换和显示兼容视图 | Python 标准库 |
| `agent_marquee/core/reducer.py` | 从事件证据保守推导单项任务状态 | Python 标准库 |
| `agent_marquee/core/registry.py` | 多来源会话隔离、去重、序号保护、过期健康标记 | Python 标准库 |
| `agent_marquee/core/attention.py` | 确定性的需处理排序与任务列表文案 | Python 标准库 |
| `agent_marquee/core/ingestion.py` | 接收、清空与读取状态的单一内核入口 | core |
| `agent_marquee/core/spool.py` | 本机事件投递、短期缓存与过期清理 | Python 标准库 |
| `agent_marquee/core/history.py` | 最近 200 条弹幕的内存历史、隐私清理 | Python 标准库 |
| `agent_marquee/core/traffic.py` | 重复事件合并、普通事件限流及批次优先级 | Python 标准库 |
| `agent_marquee/adapters/` | 各智能体 Hook 输入到 Event v1 的转换；只允许安全摘要出站 | core |
| `agent_marquee/emit.py` | Hook 统一入口，读取 stdin JSON，选择适配器 | adapters + core |
| `agent_marquee/send.py` | 第三方工具显式发送 Event v1 | core |
| `agent_marquee/install.py` | 对每个工具单独合并/卸载 Hook 配置 | Python 标准库 |
| `agent_marquee/display/macos.py` | macOS 原生悬浮层、菜单栏入口、接入/历史/设置窗口 | AppKit + core |
| `agent_marquee/display/icons.py` | 优先读取本机工具图标（Codex 专用图标），为缺失来源绘制字母标识 | AppKit |
| `agent_marquee/display/sample_events.py` | 仅 `--demo` 使用的假数据 | Python 标准库 |
| `agent_marquee/core/settings.py` | 用户目录设置与旧演示设置迁移 | Python 标准库 |
| `agent_marquee/core/sources.py` | 自定义来源登记、显示名称与安全存储 | Python 标准库 |
| `agent_marquee/bridge.py` | 可选的本机 HTTP 接口，密钥校验后复用 Event v1 | Python 标准库 |
| `agent_marquee/notifications/` | 可选的 macOS 通知读取、微信识别和短期去重；默认关闭 | ApplicationServices + core |

## Event v1

`version`, `agent`, `event`, `kind`, `message`, `project`, `session_id`, `turn_id`, `occurred_at`，以及可选的 `detail` 和 `open_url`。`kind` 为 `working`、`success`、`attention` 或 `error`。`agent` 是小写短标识。`detail` 由适配器从许可字段提取，最长 48 字；仅在用户选择“部分详情”时显示。`open_url` 仅接受不含账号密码的 HTTP(S) 地址，用户从历史记录主动打开。显示层可用 `agent + project` 区分并行任务。

协议默认只发送事件类别、短句和项目名。不得将原始提问、思考、命令全文、工具输入/输出、完整路径或凭证塞进事件。`detail` 当前只允许少量程序名和文件 basename；`project` 是工作目录最后一级名称。启用隐私模式后显示层会进一步隐藏来源和内容。显示层的 `ProgressGate` 默认压缩普通工具事件，重要事件不压缩。

微信通知接入器是单独的用户授权来源：默认只发送“有新消息”，显式开启预览后才把当前通知中的发送人和短文本放进 `message`。它只扫描 Notification Center 当前可见窗口的辅助功能树，不读取微信数据库、聊天窗口或系统通知数据库。读取到的原始文本不持久化；选中预览后生成的事件会短暂经过本机 spool，并遵循相同的历史与隐私处理。

## Event v2 与当前任务

Event v2 是面向状态推导的观察事件，包含 `event_type`、`event_id`、`occurred_at`、`agent`，以及可选的 `source_instance`、`session_id`、`turn_id`、`task_id`、`parent_task_id`、`trace_id`、`sequence` 和经过筛选的显示字段。v1 仍是命令、Hook 和本机 HTTP 的稳定入口；接收器保留其显示效果，并在内存中将可识别的 v1 事件转换为 v2。新来源可直接投递 v2，不需要修改原有适配器。没有 `session_id` 的事件只作通知，不进入任务列表。

状态推导由纯函数 reducer 完成，按来源实例、会话和任务/轮次隔离。`Stop` 仅映射为 `turn_stop_observed`，不会宣称任务完成；`PermissionRequest` 只产生有 30 秒期限的“可能需要批准”，只有明确可见的批准请求事件才进入“需要批准”。工具结束不等于任务结束；会话结束让未终结任务回到“状态未确认”；事件过久未更新只标记为 stale，不推测阻塞。重复事件、旧序号和已结束会话的迟到事件不会重新推进状态。隐私模式清空内存任务状态，暂停时任务列表暂不展示。

当前任务列表按明确的需批准、需输入、失败、待确认、完成和工作中排序。这份状态是本机事件的保守视图，不能替代源工具自身的任务状态。v2 的已完成、失败和取消事件需要来源提供可靠证据；现有 Hook 尚不自动发送“整项任务已完成”。

## 本机传输

生产者将单个 JSON 事件原子写入 `/tmp/agentbarrage-<uid>/`，目录权限为 `0700`。此内部路径保留旧名称，以兼容已运行的旧版 Hook 进程。显示层轮询、校验并消费，超过 45 秒的事件丢弃。文件传输不要求智能体 Hook 拥有网络或 Unix socket 权限；弹幕程序短暂退出时事件可等待其重新启动。未来可加其他传输实现，但不能改变 Event v1 语义。

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
