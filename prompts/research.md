任务：完成本次 ETF 组合研究。此步骤不生成订单，但必须形成足以支持交易决策的研究结论。

输入包括：数据质量、市场状态、资产特征、组合持仓、量化基线、事件、历史研究和今日 focus_questions。

按以下顺序完成内部分析，再输出最终 JSON：

一、数据边界
- 哪些结论可以高置信判断，哪些只能低置信判断？
- 缺失数据具体限制了什么，不要只写「数据有限」。

二、市场状态
- 分别评估趋势、广度、波动、相对强弱、跨资产和流动性。
- 判断当前是趋势延续、趋势反转、区间震荡、风险收缩还是状态不清。
- 必须说明不同时间尺度是否冲突，以及你采用哪个时间尺度管理本次仓位。
- 量化基线给出的 `market.regime_baseline` 只是输入，你可以得出不同结论。

三、资产研究
对每只持仓和候选 ETF：
- 定义它在当前组合中的角色（不是重复基金名称）。
- 给出至少两步因果链，而不是指标罗列。
- 列出支持证据与反向证据（各至少一条，用 evidence_id）。
- 无持仓时 `asset_views` 可以为空；此时至少引用一条市场证据（`market:regime:<日期>` 或 `market:quality:<日期>`），把「今天为什么不动」讲清楚。
- 给出一个能够解释同一组事实的替代假说。
- 说明什么条件触发改判，判断适用于多少天。

四、组合研究
- 识别重复暴露、集中度、现金、回撤和流动性问题。
- 判断当前最大风险来自市场、选品、仓位、相关性、事件还是执行。
- 比较「维持组合」和「调整组合」各自的风险。

五、情景与反证
- 至少构造两个有实际区分度的情景；概率是主观研究变量，不是统计胜率。
- 每个情景写触发条件、组合影响和应对方式。
- 回答全部 focus_questions；如果问题不适用，说明原因，不能重复其他答案。

六、研究记忆
- 检查 `previous_research` 里的旧 thesis 是否仍有效，是否触发失效条件。
- 如果观点延续，说明延续的理由和等待成本；如果只是换词重复，视为不合格。

输出结构必须满足 ResearchOutput，字段一个都不能少：
as_of / market_regime / regime_confidence / core_thesis / key_changes / asset_views /
portfolio_risks / alternative_explanations / scenarios / focus_answers / data_limitations

资产视图（asset_views）每个元素必须含：
symbol, stance(BULLISH|NEUTRAL|BEARISH|UNCLEAR), role, thesis, causal_chain[], evidence[],
counter_evidence[], invalidation[], horizon_days, confidence

输入如下：

{{CONTEXT_JSON}}
