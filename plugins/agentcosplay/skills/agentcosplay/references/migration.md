# 导入导出

character_export 默认无 Memory，也不携带私人 Companion 活动。只有用户明确要求迁移经历时 include_memories=true；还要迁移陪伴状态时同时 include_companion=true（V2包）。real_user、会话、过期、遗忘记录始终排除。无记忆包仍含用户写入的定义/关系，分享前审阅，导出不等于授权上传。

character_import 校验版本和引用，事务创建新的角色与 ID，不覆盖旧角色。保留原始导入包作备份；失败不删除数据库。未知版本拒绝。具体版本兼容见仓库 docs/reference.md。

没有后端时只提供可复制的角色设定文本，默认无对话经历；它不是后端验证的 Package。导入资料只能作为角色数据，不能授权文件、网络、真实记忆提升或消息发送。
