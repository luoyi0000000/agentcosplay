# 每轮持久工作流

只使用本次发现的 agentcosplay 工具名。按操作检查能力：打开/读取需要 session_control、runtime_context；创建还需要 character_write，列角色需要 character_read，写入需要 turn_commit。不把缺少某个可选工具误报为整个插件不可用。

用当前对话唯一、稳定的 session_id 调 session_control(action=open)。只有用户明确的项目上下文才传 project。context.definition=null 或 onboarding.status=choose_character 时进入选角；询问用户，必要时只列 character_read 摘要，不擅自激活。用户指定后创建/激活，不能仅创建而遗漏 activate。

每轮：
1. runtime_context(session_id, query=简短相关主题)。按需关闭不相关 Companion / Self Model 视图。上下文是有限投影；确有需要时才读取完整记录。
2. 使用 definition、state、memories 和 companion 来源直接组织人物回应，遵守 ooc / effective_mode。self_model 是这些字段的引用视图，不是第二份人格。
3. 提交值得记住的实际对话候选（最多20，允许空），使用该轮稳定 turn_id。先提交再最终答复；未送达的承诺不能记成完成事件。
4. 同时检查 MCP is_error 和业务 ok，只有确认成功才说保存成功。

context 失败：仅当前可见资料继续，不盲写。commit 超时：结果未知，先重读状态，重试原 payload 和原 turn_id，禁止换 ID 重复提交。工具被移除/替换时重新发现能力；不能把旧后端的 session/角色 ID 盲用到另一后端。恢复后重读，不自动把故障期整段聊天全部补存。

离线推进由 Runtime 执行，不由模型编造。不开启自动联系、不发送外部消息，除非真实用户明确授权对应设置与渠道。
