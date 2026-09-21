# 导入导出

character_export 默认 V3，无记忆、原始事件、位置、身份绑定或投递授权。用户要求迁移经历时 include_memories=true；陪伴还要 include_companion=true；完整私人证据/成长历史等用 include_private_knowledge=true 并先审阅内容。导出不等于授权上传。

character_import 需要 operation_id，接受 V1/V2/V3 并创建新角色。旧记录和导入证据保持不可信，不变成用户事实或新成长证据；导入事实/叙事归档，视觉原型重新待确认。原始包不改写。SQLite V1→V2 自动先备份再迁移，撤销旧跨角色共享。不要删除数据库来解决版本问题。
