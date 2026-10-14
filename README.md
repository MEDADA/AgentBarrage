# AgentBarrage

![AgentBarrage 弹幕气泡标志](assets/agentbarrage-logo.svg)

AgentBarrage 将 Codex、Claude Code、CodeBuddy Code 等本机智能体的工作状态显示为 macOS 桌面弹幕。不同工具通过独立适配器接入同一事件协议；内置适配器只发送预设短句和经过筛选的详情。

**当前状态：正式程序可从源码运行；项目计划在 GitHub 公开源码，暂无 `.app` 安装包发布计划。** 原生悬浮窗、接入管理、样式设置、内存历史、三个 Hook 适配器和本机发送命令已经实现。Codex Hook 已在本机实际触发并显示。Claude Code 与 CodeBuddy Code 的适配器通过模拟 Hook 输入验证，真实产品覆盖仍需验收。CodeBuddy 桌面版/IDE 的实际接入方式仍需验证。

## 在 macOS 启动

需要 macOS、Python 3.11 或更新版本。在项目根目录运行：

```sh
python3 -m venv .venv
./.venv/bin/python -m pip install '.[macos]'
./.venv/bin/agent-barrage
```

本机若已安装 PyObjC，也可直接运行 `python3 bin/agent-barrage`。这是正式入口，默认只显示真实接入事件，没有模拟按钮。启动后右上角出现控制窗和菜单栏弹幕气泡图标，透明弹幕显示在当前系统窗口之上；程序不占用程序坞。关闭控制窗后可从菜单栏重新打开，选择“退出 AgentBarrage”才会退出程序。使用包安装后，可直接调用虚拟环境中的 `agent-barrage`、`agent-barrage-hooks`、`agent-barrage-send` 和可选的 `agent-barrage-bridge`。

开发者如需在本机生成独立 `.app`（需要 Xcode Command Line Tools）：

```sh
./.venv/bin/python -m pip install pyinstaller pillow
PATH="$PWD/.venv/bin:$PATH" sh packaging/macos/build.sh
open dist/AgentBarrage.app
```

构建结果在 `dist/AgentBarrage.app`，它可直接运行且不依赖源码 Python 环境，但目前只有临时签名、没有公证，仅供本机试用。双击后从“智能体接入”安装 Hooks；打包版的 Hook 和自定义来源命令都通过应用内置的后台入口发送。移动 `.app` 后请重新安装 Hooks，以更新绝对路径。

要单独查看假数据动效，请运行 `./demo/run.sh`、`python3 bin/agent-barrage --demo` 或 `./.venv/bin/agent-barrage --demo`。只有演示模式才出现“工作 / 需批准 / 完成 / 错误”和循环播放按钮。

“弹幕设置”可调整样式、文字颜色、区域、字号、滚动速度、透明度和行间距。参考 [B 站的弹幕控制项](https://www.bilibili.com/video/BV1Wp4y1P7KU/)，还加入了适合桌面通知的设置：

- **文字颜色：macOS 原生颜色卡。** 点击色块可自由选色；在白色页面上使用纯文字样式时，可选择深色文字。程序不读取屏幕背景，也不需要屏幕录制权限。

- **内容：简洁摘要 / 部分详情。** 默认只显示预设工作状态；选择“部分详情”后，可附上经过适配器筛选的程序名或文件名。不会展示原始提问、命令参数、文件内容或工具输出。若某工具没有可安全提取的详情，仍只显示摘要。
- **进度弹幕：精简 / 全部。** 默认合并同一会话 3 秒内的普通工具开始事件，并省略普通工具结束提示；失败、需处理与完成事件仍显示。“全部”展示每条 Hook 事件。
- **播放方式：滚动 / 固定停留。** 固定弹幕按设定时长停留；区域决定显示在顶部、中部或底部。
- **区域占比与同屏密度。** 控制可使用的屏幕高度，以及最多同时显示多少条。密度满时优先移走普通工作提示，保留需处理和错误提示。
- **类型过滤。** 可隐藏普通工作提示，或只看需处理与错误事件。
- **来源图标。** Codex 优先读取本机已安装程序的专用 Codex 图标，其他内置来源读取应用图标；找不到时使用来源字母标识。可在设置中关闭。
- **显示器与动态效果。** 可只在主屏幕显示；连接或断开显示器时悬浮层会重建。打开“减少动画”或启用 macOS 的减少动态效果后，滚动弹幕会改为固定停留。

短时间内重复的事件会合并；普通工作事件有速率上限。需处理和错误事件在同批事件中优先显示。

设置保存于 `~/Library/Application Support/AgentBarrage/settings.json`；首次运行会从旧的 `demo/settings.json` 迁移已有偏好。“历史记录”显示最近 200 条已展示事件，可清空；记录只在内存中，退出程序或开启隐私模式后会消失。隐私模式会隐藏屏幕上的来源与消息，并清空旧历史。

卸载时，先在“智能体接入”分别卸载已启用的 Hooks，退出应用，再移走 `.app`。如果不再需要偏好、自定义来源和图标，可自行删除 `~/Library/Application Support/AgentBarrage/`；默认保留这些用户数据，便于重新安装。

检查环境和运行测试：

```sh
./.venv/bin/python -c 'import AppKit; print("PyObjC OK")'
python3 -m unittest discover -s tests -v
```

## 发送一条测试弹幕

保持桌面程序运行，在另一个终端执行：

```sh
python3 bin/agent-barrage-send --agent my-agent --kind success --message "测试完成" --project Demo
```

`--agent` 使用小写字母、数字和连字符；`--kind` 可选 `working`、`success`、`attention`、`error`。任何本机工具均可调用此命令，但发送者应确保 `--message` 适合显示在屏幕上。来源有网页任务地址时，可加 `--url 'https://example.com/task/123'`；历史记录会显示“打开来源”。链接仅在用户点击后打开，不会自动访问。内置 Hook 当前没有可靠的来源任务链接，因此不会猜测地址。

## 接入智能体 Hooks

主控制窗的“智能体接入”会显示 Codex、Claude Code、CodeBuddy Code 各自的 Hook 配置状态，并提供单独安装/更新与卸载按钮。安装只修改对应工具的用户级配置，不会自动授权 Hook；Codex 和 CodeBuddy Code 仍需在各自的 `/hooks` 审查。其他智能体可通过前述 `agent-barrage-send` 命令接入。

对任意 AI 工具或对话，可在“智能体接入 → 添加或管理其他来源”登记名称和标识，复制自动生成的命令，并发送测试弹幕。支持 Hook 命令、本机自动化，以及默认关闭的带密钥本机 HTTP 接口。接入方式和网页对话的边界见[任意来源接入指南](./INTEGRATIONS.md)。

也可以在终端管理。先预览将修改的配置路径和事件，再执行安装：

```sh
python3 bin/agent-barrage-hooks --agent codex --dry-run
python3 bin/agent-barrage-hooks --agent codex
python3 bin/agent-barrage-hooks --agent claude-code
python3 bin/agent-barrage-hooks --agent codebuddy
```

安装器合并用户级 JSON 配置，保留其他设置与 Hook。已有配置第一次修改时会生成同目录的 `.agentbarrage-backup` 备份。Hook 命令引用当前仓库的绝对路径，因此**移动或删除仓库前先卸载 Hooks**；移动后如需继续使用，请从新路径重新安装。Codex 和 CodeBuddy Code 的非托管 Hooks 还需在各自的 `/hooks` 中完成信任审查，已运行的会话可能需要重启才加载新配置。

单独卸载某个工具：

```sh
python3 bin/agent-barrage-hooks --agent codex --uninstall
python3 bin/agent-barrage-hooks --agent claude-code --uninstall
python3 bin/agent-barrage-hooks --agent codebuddy --uninstall
```

关闭桌面程序不会自动删除 Hook 配置。安装器拒绝覆盖符号链接形式的设置文件；遇到这种配置，请先人工确认目标文件和安装方式。

## 开发与开源状态

- [架构与隐私边界](./ARCHITECTURE.md)
- [任意来源接入指南](./INTEGRATIONS.md)
- [产品计划](./PLAN.md)
- [贡献指南](./CONTRIBUTING.md)
- [安全问题反馈](./SECURITY.md)
- [发布检查清单](./RELEASE.md)
- [MIT 许可证](./LICENSE)

核心和适配器只依赖 Python 标准库；显示层位于 `agent_barrage/display/macos.py`，依赖 macOS AppKit/PyObjC。GitHub 源码开源的检查项和后续产品验收见 [发布检查清单](./RELEASE.md)。
