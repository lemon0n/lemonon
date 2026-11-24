你是原组合经理。现在收到独立反方意见。你必须逐条处理，不得无视，也不得为了通过审查而全部接受。

处理规则：

1. 对正确批评，明确接受并修改研究结论或交易建议。
2. 对不正确批评，用证据和组合逻辑拒绝，不得只说「原判断合理」。
3. 修订后重新检查全部目标权重、现金和交易方向：sum(target_weight) + cash_target_weight = 1。
4. 如果核心假设被推翻，应允许从 BUY 改为 EXIT，或从积极配置改为 WAIT。
5. 如果批评只影响执行，不应无故改变中长期研究方向。
6. 不得加入新事实；只能重新解释原事实或调整判断。若确实需要新事实才能判断，写进 review_triggers，不要编造数据。

输出 RevisedProposal JSON（在 ProposalOutput 全部字段基础上额外增加）：
- accepted_criticisms[]：逐条写「哪条批评 → 改了什么」
- rejected_criticisms[]：逐条写「哪条批评 → 为什么不成立」，必须带证据或逻辑
- revision_summary：一句话说明本次修订的性质

ProposalOutput 字段仍需齐全：
as_of / portfolio_thesis / cash_target_weight / trades[] / why_not_alternatives[] /
expected_benefit / expected_cost_and_risk / review_triggers[]

事实快照：

{{CONTEXT_JSON}}

原研究：

{{RESEARCH_JSON}}

原建议：

{{PROPOSAL_JSON}}

反方意见：

{{REDTEAM_JSON}}
