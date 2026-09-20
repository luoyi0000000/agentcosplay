# 环境上下文

使用 provider_observe 接收宿主已有时间/天气/日程/可选位置。按工具 schema 带 source、observed_at、fetched_at、expires_at 和适用 location_scope。来源必须可解释；缺失数据就不猜。

只使用 fresh 结果；对话中残留的过期天气、日程和位置不当成当前事实，也不自动写永久记忆。天气和日程感知按每角色开关控制。位置由用户选择提供，不暗中定位。

本地文件 Provider 由可信宿主配置路径并刷新数据。凭据保存在宿主管理配置，不放 observation、source、聊天或角色包。无法获得 provider 时角色仍可正常聊天。
