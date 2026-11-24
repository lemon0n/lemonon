# -*- coding: utf-8 -*-
"""LLM 研究决策层（《ETF LLM 交易分析系统详细执行书》对应实现）。

分层（对应执行书 2.1）：
    数据与状态准备      etfquant.pipeline / datasource / portfolio.positions
    确定性数据处理      features / quality / signals / evidence
    LLM 研究决策        llm.pipeline（Research → Proposal → Red Team → Revision）
    确定性交易风控      llm.risk / llm.orders
    结果与复盘          llm.storage / llm.report

约定：
    · 本包只在运行时导入 pydantic 等可选依赖，缺失时 raise LLMUnavailable；
    · 模型不可用时状态一律 LLM_FAILED，绝不把规则模板包装成新的模型建议；
    · 账户原值只写 data/runs/（已 gitignore），页面只接收脱敏后的权重视图。
"""


class LLMUnavailable(RuntimeError):
    """LLM 层不可用（缺依赖 / 未配置 / 服务离线）。调用方应降级而不是伪造建议。"""


__all__ = ['LLMUnavailable']
