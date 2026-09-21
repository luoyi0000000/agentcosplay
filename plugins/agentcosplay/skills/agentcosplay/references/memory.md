# 记忆与事实

RawEvent ≠ Memory ≠ Fact ≠ Narrative。MemoryProposal 必须带同人物有效原始证据；低价值内容可仅留 RAW_ONLY。显式“记住”才能设置 explicit_remember。项目内容用 domain=project，不注入人物性格。凭据不能保存；敏感资料只在用户明确同意并进入 OOC 后保存。

时间查询通过 memory_recall.request 指定 intent 和真实时间窗口/时区，不搜索“上周”这个词。只在用户选择现实资料且相关时 real=true。EXACT_QUOTE 用原始证据，不把摘要包装成原话。记忆重复召回不能增加信任度。

更正、忘记和提升前 enter_ooc，再 memory_recall 取得短时 allowlist；提交 operation_id、目标 ID 和 grant。提升只能使用新的直接用户证据和真实且保存的确认；导入、转发、媒体和模拟不可提升。Fact 更正使用相同 semantic_key 的 SUPERSEDE，不能把“不喜欢了”丢成重复。
