# -*- coding: utf-8 -*-
"""数据契约：LLM 决策层唯一的结构化对象（执行书 5.1）。

设计纪律：
  · 全部 extra='forbid'：模型多写字段直接报错，避免「看起来合规」的自由发挥；
  · 方向与权重必须自洽：BUY/ADD 提权重、SELL/REDUCE 降权重、EXIT 归零、HOLD/WAIT 不动；
  · 权重一律是占「含现金总资产」的比例（0–1），不是百分数，不在层间换口径；
  · 模型只输出建议对象，能否执行由 llm.risk 决定——本模块不做风控判断。
"""
from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

WEIGHT_TOL = 1e-6


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class Action(str, Enum):
    BUY = 'BUY'          # 新建仓位
    SELL = 'SELL'        # 卖出（保留部分）
    ADD = 'ADD'          # 加仓
    REDUCE = 'REDUCE'    # 减仓
    EXIT = 'EXIT'        # 清仓
    HOLD = 'HOLD'        # 维持
    WAIT = 'WAIT'        # 观望（不持有或暂不动作）


INCREASE = {Action.BUY, Action.ADD}
DECREASE = {Action.SELL, Action.REDUCE, Action.EXIT}
NO_CHANGE = {Action.HOLD, Action.WAIT}


class EvidenceRef(StrictModel):
    evidence_id: str = Field(min_length=3)
    claim: str = Field(min_length=2)


class Scenario(StrictModel):
    name: str = Field(min_length=2)
    probability: float = Field(ge=0, le=1)
    trigger: str = Field(min_length=2)
    portfolio_implication: str = Field(min_length=2)
    response: str = Field(min_length=2)


class AssetView(StrictModel):
    symbol: str = Field(min_length=4)
    stance: Literal['BULLISH', 'NEUTRAL', 'BEARISH', 'UNCLEAR']
    role: str = Field(min_length=2, description='该资产在组合中的角色，不是泛泛介绍')
    thesis: str = Field(min_length=2)
    causal_chain: list[str] = Field(min_length=2)
    evidence: list[EvidenceRef] = Field(min_length=2)
    counter_evidence: list[EvidenceRef] = Field(min_length=1)
    invalidation: list[str] = Field(min_length=1)
    horizon_days: int = Field(gt=0)
    confidence: float = Field(ge=0, le=1)


class TradeAdvice(StrictModel):
    symbol: str = Field(min_length=4)
    action: Action
    current_weight: float = Field(ge=0, le=1)
    target_weight: float = Field(ge=0, le=1)
    priority: int = Field(ge=1, le=5)
    horizon_days: int = Field(gt=0)
    rationale: str = Field(min_length=2)
    evidence: list[EvidenceRef] = Field(min_length=1)
    trigger: str = Field(min_length=2)
    invalidation: str = Field(min_length=2)
    execution_rule: str = Field(min_length=2)
    confidence: float = Field(ge=0, le=1)

    @model_validator(mode='after')
    def check_weight_direction(self):
        delta = self.target_weight - self.current_weight
        if self.action in INCREASE and delta <= WEIGHT_TOL:
            raise ValueError('%s: 买入方向必须提高目标权重（%.4f → %.4f）'
                             % (self.symbol, self.current_weight, self.target_weight))
        if self.action in DECREASE and delta >= -WEIGHT_TOL:
            raise ValueError('%s: 卖出方向必须降低目标权重（%.4f → %.4f）'
                             % (self.symbol, self.current_weight, self.target_weight))
        if self.action == Action.EXIT and abs(self.target_weight) > WEIGHT_TOL:
            raise ValueError('%s: EXIT 的目标权重必须为 0' % self.symbol)
        if self.action in NO_CHANGE and abs(delta) > WEIGHT_TOL:
            raise ValueError('%s: HOLD/WAIT 不应改变目标权重' % self.symbol)
        return self


def _check_trades(trades: list[TradeAdvice]) -> None:
    seen: dict[str, Action] = {}
    for t in trades:
        if t.symbol in seen:
            raise ValueError('同一标的出现多条建议：%s' % t.symbol)
        seen[t.symbol] = t.action


class ResearchOutput(StrictModel):
    as_of: str = Field(min_length=8)
    market_regime: str = Field(min_length=2)
    regime_confidence: float = Field(ge=0, le=1)
    core_thesis: str = Field(min_length=2)
    key_changes: list[str]
    asset_views: list[AssetView]
    portfolio_risks: list[str]
    alternative_explanations: list[str] = Field(min_length=1)
    scenarios: list[Scenario] = Field(min_length=2)
    focus_answers: list[str]
    data_limitations: list[str]

    @model_validator(mode='after')
    def check_views(self):
        symbols = [v.symbol for v in self.asset_views]
        if len(symbols) != len(set(symbols)):
            raise ValueError('asset_views 存在重复标的')
        total = sum(s.probability for s in self.scenarios)
        if not 0.5 <= total <= 1.5:
            raise ValueError('情景概率合计 %.3f 明显异常（主观概率也应大致归一）' % total)
        return self


class ProposalOutput(StrictModel):
    as_of: str = Field(min_length=8)
    portfolio_thesis: str = Field(min_length=2)
    cash_target_weight: float = Field(ge=0, le=1)
    trades: list[TradeAdvice]
    # 无交易（空仓/无持仓）时的证据落点：结论可以有引用，不必硬塞进 trades
    evidence: list[EvidenceRef] = []
    why_not_alternatives: list[str]
    expected_benefit: str
    expected_cost_and_risk: str
    review_triggers: list[str]

    @model_validator(mode='after')
    def check_unique(self):
        _check_trades(self.trades)
        return self

    def totals(self) -> tuple[float, float]:
        """返回 (目标风险资产合计, 含现金合计)。"""
        gross = sum(t.target_weight for t in self.trades)
        return gross, gross + self.cash_target_weight


class RedTeamIssue(StrictModel):
    severity: Literal['LOW', 'MEDIUM', 'HIGH', 'FATAL']
    target: str = Field(min_length=1)
    issue: str = Field(min_length=2)
    evidence: list[EvidenceRef]
    required_change: str = Field(min_length=2)


class RedTeamOutput(StrictModel):
    verdict: Literal['ACCEPT', 'REVISE', 'REJECT']
    issues: list[RedTeamIssue]
    missing_analysis: list[str]
    best_alternative: str


class RevisedProposal(ProposalOutput):
    accepted_criticisms: list[str]
    rejected_criticisms: list[str]
    revision_summary: str = Field(min_length=2)


class RiskViolation(StrictModel):
    code: str = Field(min_length=2)
    severity: Literal['REPAIRABLE', 'FATAL']
    symbol: Optional[str] = None
    message: str = Field(min_length=2)
    observed: Optional[str] = None
    required: Optional[str] = None


class RiskResult(StrictModel):
    status: Literal['APPROVED', 'NEEDS_REPAIR', 'REJECTED']
    violations: list[RiskViolation]
    checked_at: str

    @property
    def fatal(self) -> bool:
        return any(v.severity == 'FATAL' for v in self.violations)


class SystemAdjustment(StrictModel):
    """系统对模型输出的数据补全记录（不是改变投资方向，必须留痕）。"""
    code: str
    kind: Literal['BACKFILL_HOLD', 'CLAMP_WEIGHT', 'DROP_UNKNOWN', 'ORDER_ROUNDING']
    detail: str


class OrderDraftModel(StrictModel):
    symbol: str
    side: Literal['BUY', 'SELL']
    quantity: int = Field(ge=0)
    reference_price: float = Field(gt=0)
    estimated_value: float = Field(ge=0)
    estimated_fee: float = Field(ge=0)
    target_weight: float = Field(ge=0, le=1)
    status: Literal['DRAFT', 'SUPPRESSED_MIN_VALUE', 'SUPPRESSED_NO_CASH',
                    'REJECTED_NOT_TRADABLE']
    note: str = ''


class FinalPlan(StrictModel):
    """最终批准计划：页面、报告、订单草案唯一读取的对象。"""
    as_of: str
    trade_date: str
    status: Literal['APPROVED', 'REJECTED', 'ABSTAIN', 'LLM_FAILED', 'LLM_MOCK']
    model_proposal: Optional[RevisedProposal] = None
    original_proposal: Optional[ProposalOutput] = None
    risk: Optional[RiskResult] = None
    research_summary: Optional[dict] = None
    redteam_verdict: Optional[str] = None
    orders: list[OrderDraftModel] = []
    system_adjustments: list[SystemAdjustment] = []
    notes: list[str] = []


class RunManifest(StrictModel):
    run_id: str
    trade_date: str
    created_at: str
    status: str
    mode: str
    model_name: str
    provider: str
    prompt_version: str
    snapshot_hash: str
    config_hash: str
    input_hash: str
    data_date: str = ''
    code_version: str = ''
    duration_seconds: float = 0.0
    usage: dict = {}
