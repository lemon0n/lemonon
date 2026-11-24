你的交易建议没有通过确定性风控。此步骤只修复风控指出的问题，不得借修复之名重新发明整套策略。

要求：

1. 逐项解决 violations（每条的 code / symbol / observed / required 都要对上）。
2. 保持仍可保留的投资逻辑；如约束使逻辑失去意义，可以取消对应交易。
3. 重新平衡目标权重与现金，使 sum(target_weight) + cash_target_weight = 1，且满足 risk_policy。
4. 在 revision_summary 与 accepted_criticisms 里说明每一项修复（格式：「CODE 标的 → 修改内容」）。
5. 不要新增交易标的，不要改掉没有问题的建议。
6. 输出 RevisedProposal JSON，不输出解释性 Markdown。

事实快照：

{{CONTEXT_JSON}}

模型建议：

{{PROPOSAL_JSON}}

风控问题：

{{VIOLATIONS_JSON}}
