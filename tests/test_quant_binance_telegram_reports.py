from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from quant_binance.telegram_reports import format_execution_quality_report, format_weekly_validation_report
from quant_binance.telegram_reports import format_runtime_telegram_report


class QuantBinanceTelegramReportsTests(unittest.TestCase):
    def test_format_weekly_validation_report_in_korean(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            base = Path(tempdir) / "quant_runtime" / "artifacts"
            base.mkdir(parents=True, exist_ok=True)
            (base / "weekly_validation_report.json").write_text(
                json.dumps(
                    {
                        "run_count": 2,
                        "total_closed_trade_count": 3,
                        "total_realized_pnl_usd": 12.34,
                        "total_live_order_count": 5,
                        "total_tested_order_count": 1,
                        "sample_progress": {
                            "required_total_closed_trade_count": 6,
                            "required_total_live_order_count": 8,
                            "remaining_closed_trade_count": 3,
                            "remaining_live_order_count": 3,
                            "ready_for_comparison": False,
                        },
                        "score_alignment_summary": [
                            {"score_bucket_label": "60-69", "trade_count": 2, "expectancy_usd": 0.8, "hit_rate": 0.5},
                            {"score_bucket_label": "70-79", "trade_count": 3, "expectancy_usd": 2.1, "hit_rate": 0.6667}
                        ],
                        "regime_summary": [
                            {"mode": "futures", "decision_count": 10, "avg_score": 61.2, "avg_net_edge_bps": 8.4}
                        ],
                        "symbol_summary": [
                            {"symbol": "BTCUSDT", "recommendation": "promote", "expectancy_usd": 2.1, "realized_pnl_usd": 6.2},
                            {"symbol": "WLDUSDT", "recommendation": "prune", "expectancy_usd": -1.2, "realized_pnl_usd": -3.5},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            text = format_weekly_validation_report(base.parent)
            self.assertIn("[주간 검증 리포트]", text)
            self.assertIn("표본 진행도", text)
            self.assertIn("추가 필요", text)
            self.assertIn("점수-수익 연결", text)
            self.assertIn("score 70-79", text)
            self.assertIn("승격 후보", text)
            self.assertIn("제외/관찰 후보", text)

    def test_format_execution_quality_report_in_korean(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            base = Path(tempdir) / "quant_runtime" / "artifacts"
            base.mkdir(parents=True, exist_ok=True)
            (base / "execution_quality_report.json").write_text(
                json.dumps(
                    {
                        "run_count": 2,
                        "live_order_count": 4,
                        "accepted_live_order_count": 3,
                        "estimated_live_acceptance_rate": 0.75,
                        "tested_order_count": 1,
                        "order_error_count": 2,
                        "executive_verdict": "tighten",
                        "executive_reason_codes": ["EXECUTIVE_TIGHTEN_BY_AUTO_MODE"],
                        "executive_replay_provenance": {
                            "primary": {
                                "summary": "mixed_root_summary_fallback:root",
                                "policy_bucket": "not_available",
                            }
                        },
                        "top_error_codes": [{"code": "40762", "count": 2}],
                        "policy_bucket_summary": [
                            {
                                "policy_bucket": "active_policy",
                                "live_order_count": 2,
                                "estimated_live_acceptance_rate": 1.0,
                                "order_error_count": 0,
                            }
                        ],
                        "symbol_order_summary": [
                            {"symbol": "BTCUSDT", "live_order_count": 2, "estimated_live_acceptance_rate": 1.0, "order_error_count": 0}
                        ],
                    }
                ),
                encoding="utf-8",
            )
            text = format_execution_quality_report(base.parent)
            self.assertIn("[실행 품질 리포트]", text)
            self.assertIn("운영 총괄 판정: tighten", text)
            self.assertIn("판정 근거 provenance: mixed_root_summary_fallback:root", text)
            self.assertIn("주요 오류 코드", text)
            self.assertIn("심볼별 주문 상태", text)
            self.assertIn("정책 버킷별 주문 상태", text)

    def test_format_runtime_telegram_report_in_korean(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            latest = Path(tempdir) / "quant_runtime" / "output" / "paper-live-shell" / "latest"
            latest.mkdir(parents=True, exist_ok=True)
            (latest / "summary.json").write_text(
                json.dumps(
                    {
                        "decision_count": 3,
                        "live_order_count": 1,
                        "tested_order_count": 0,
                        "exchange_live_futures_positions": [
                            {"symbol": "BTCUSDT", "holdSide": "long", "unrealizedPL": "1.2"}
                        ],
                        "live_orders": [
                            {
                                "symbol": "BTCUSDT",
                                "side": "buy",
                                "quantity": 0.01,
                                "accepted": True,
                                "order_id": "oid-1",
                            }
                        ],
                        "self_healing": {
                            "recent_events": [
                                {
                                    "category": "live_entry_starvation",
                                    "automatic_action": "refresh_state_and_retry_next_cycle",
                                    "status": "applied",
                                }
                            ]
                        },
                    }
                ),
                encoding="utf-8",
            )
            (latest / "overview.json").write_text(
                json.dumps({"updated_at": "2026-03-15T02:11:00+00:00", "status": "healthy"}),
                encoding="utf-8",
            )
            (Path(tempdir) / "quant_runtime" / "live_supervisor_health.json").write_text(
                json.dumps({"status": "healthy"}),
                encoding="utf-8",
            )
            text = format_runtime_telegram_report(Path(tempdir) / "quant_runtime", event="started")
            self.assertIn("[오픈클로 실거래 요약 리포트]", text)
            self.assertIn("보유 포지션", text)
            self.assertIn("최근 체결 주문", text)
            self.assertIn("자동복구 상태", text)


if __name__ == "__main__":
    unittest.main()
