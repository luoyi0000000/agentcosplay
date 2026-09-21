# 陪伴状态

companion_control 在 OOC 先读取，再携 operation_id 与 allowlist 更新设置。自动目标/习惯/话题使用有证据的 companion_update，已有目标修改须先读 grant；情绪使用 affect_effects。Affect、Attention、Embodiment 与人格分开，不能为沉浸感自行开启主动联系或生活模拟。

模拟仅白名单日常，永远标 simulated_life；不制造疾病、冲突、恋爱或用户在场经历。runtime_doctor 的 maintenance_operation_id 驱动一次统一维护，由宿主定时器安排。Daily reflection 是派生叙事，不能自动成为证据。数字内部状态由 Runtime 投影成语义，不把整库塞进 prompt。
