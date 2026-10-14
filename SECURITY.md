# 安全问题反馈

本项目仍是本地原型。请不要把凭证、原始对话、命令输出或其他敏感数据提交到公开 issue。

若发现可利用的安全问题，请通过 GitHub 仓库的 **Security → Report a vulnerability** 私密报告。仓库公开前，维护者需要先开启 GitHub Private Vulnerability Reporting；未开启前不要公开包含复现凭证的报告。

Hook 适配器只应发送预设短句和最少的会话元数据。安装器应保留已有配置并仅移除自身注册的处理器。任何增加采集范围的改动都需要在文档中明确说明。
