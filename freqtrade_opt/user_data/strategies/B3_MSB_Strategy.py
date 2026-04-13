"""
B3 Market Structure Break (MSB) Strategy - freqtrade IStrategy
==============================================================
기존 quant_binance B3 MSB 전략을 freqtrade Hyperopt용으로 포팅.

원본: scripts/optimize_b3_msb.py
핵심 로직:
  1. Swing high/low 감지 (lookback window)
  2. 돌파 확인 (breakout buffer)
  3. ATR 기반 TP/SL
  4. 트렌드 필터 (EMA slope, ADX)
"""
from freqtrade.strategy import IStrategy, IntParameter, DecimalParameter, CategoricalParameter
from pandas import DataFrame
import talib.abstract as ta
import numpy as np


class B3_MSB_Strategy(IStrategy):
    """B3 Market Structure Break with Hyperopt parameters."""

    INTERFACE_VERSION = 3
    timeframe = "1h"

    # 최소 ROI - Hyperopt이 최적화
    minimal_roi = {"0": 0.1}

    # 스탑로스 - ATR 기반이므로 여기선 안전장치
    stoploss = -0.10

    # 포지션 설정
    can_short = True
    use_exit_signal = True
    exit_profit_only = False

    # ── Hyperopt 파라미터 ──
    # Swing window
    swing_window = IntParameter(8, 40, default=15, space="buy", optimize=True)

    # ATR TP multiplier
    atr_tp_mult = DecimalParameter(1.5, 6.0, default=4.0, decimals=1, space="buy", optimize=True)

    # ATR SL multiplier (TP의 반대편)
    atr_sl_mult = DecimalParameter(0.8, 3.0, default=1.0, decimals=1, space="buy", optimize=True)

    # Breakout buffer %
    breakout_buffer = DecimalParameter(0.0, 0.5, default=0.1, decimals=2, space="buy", optimize=True)

    # 최소 스윙 크기 (ATR 배수)
    min_swing_atr = DecimalParameter(0.3, 2.0, default=0.5, decimals=1, space="buy", optimize=True)

    # ADX 최소값 (트렌드 필터)
    adx_min = IntParameter(0, 35, default=20, space="buy", optimize=True)

    # EMA slope 필터
    use_ema_filter = CategoricalParameter([True, False], default=True, space="buy", optimize=True)

    # RSI 필터
    rsi_upper = IntParameter(55, 80, default=70, space="buy", optimize=True)
    rsi_lower = IntParameter(20, 45, default=30, space="buy", optimize=True)

    # Volume z-score 최소
    vol_z_min = DecimalParameter(0.0, 2.0, default=0.0, decimals=1, space="buy", optimize=True)

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """지표 계산 - 모든 파라미터 조합에서 공유."""

        # ATR
        dataframe["atr14"] = ta.ATR(dataframe, timeperiod=14)

        # EMA
        dataframe["ema20"] = ta.EMA(dataframe, timeperiod=20)
        dataframe["ema50"] = ta.EMA(dataframe, timeperiod=50)
        dataframe["ema100"] = ta.EMA(dataframe, timeperiod=100)
        dataframe["ema50_slope"] = dataframe["ema50"].diff(3)

        # ADX
        dataframe["adx"] = ta.ADX(dataframe, timeperiod=14)
        dataframe["plus_di"] = ta.PLUS_DI(dataframe, timeperiod=14)
        dataframe["minus_di"] = ta.MINUS_DI(dataframe, timeperiod=14)

        # RSI
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["rsi7"] = ta.RSI(dataframe, timeperiod=7)

        # Bollinger Bands
        bb = ta.BBANDS(dataframe, timeperiod=20, nbdevup=2.0, nbdevdn=2.0)
        dataframe["bb_upper"] = bb["upperband"]
        dataframe["bb_lower"] = bb["lowerband"]
        dataframe["bb_mid"] = bb["middleband"]
        dataframe["bb_width"] = (dataframe["bb_upper"] - dataframe["bb_lower"]) / dataframe["bb_mid"]

        # Volume z-score
        dataframe["vol_ma20"] = dataframe["volume"].rolling(20).mean()
        dataframe["vol_std20"] = dataframe["volume"].rolling(20).std()
        dataframe["vol_z"] = (
            (dataframe["volume"] - dataframe["vol_ma20"])
            / dataframe["vol_std20"].replace(0, 1e-9)
        )

        # MACD
        macd = ta.MACD(dataframe, fastperiod=12, slowperiod=26, signalperiod=9)
        dataframe["macd"] = macd["macd"]
        dataframe["macd_signal"] = macd["macdsignal"]
        dataframe["macd_hist"] = macd["macdhist"]

        # 다양한 swing window에 대해 swing high/low 사전 계산
        for sw in range(8, 41):
            dataframe[f"swing_high_{sw}"] = dataframe["high"].rolling(sw).max()
            dataframe[f"swing_low_{sw}"] = dataframe["low"].rolling(sw).min()

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """진입 시그널."""
        sw = self.swing_window.value
        buf = self.breakout_buffer.value / 100.0
        min_sw = self.min_swing_atr.value
        adx_min = self.adx_min.value
        use_ema = self.use_ema_filter.value
        vol_z_min = self.vol_z_min.value

        swing_high = dataframe[f"swing_high_{sw}"].shift(1)  # 이전 봉까지의 swing
        swing_low = dataframe[f"swing_low_{sw}"].shift(1)
        swing_range = swing_high - swing_low

        # 최소 스윙 크기
        min_range = min_sw * dataframe["atr14"]

        # Long: close > swing_high * (1 + buffer)
        long_breakout = dataframe["close"] > swing_high * (1.0 + buf)

        # Short: close < swing_low * (1 - buffer)
        short_breakout = dataframe["close"] < swing_low * (1.0 - buf)

        # 공통 필터
        swing_ok = swing_range >= min_range
        atr_ok = dataframe["atr14"] > 0
        adx_ok = dataframe["adx"] >= adx_min if adx_min > 0 else True
        vol_ok = dataframe["vol_z"] >= vol_z_min if vol_z_min > 0 else True

        # EMA 필터
        if use_ema:
            ema_long = dataframe["ema50_slope"] > 0
            ema_short = dataframe["ema50_slope"] < 0
        else:
            ema_long = True
            ema_short = True

        # RSI 필터 (과매수/과매도 회피)
        rsi_long_ok = dataframe["rsi"] < self.rsi_upper.value
        rsi_short_ok = dataframe["rsi"] > self.rsi_lower.value

        # Long 진입
        dataframe.loc[
            long_breakout & swing_ok & atr_ok & adx_ok & vol_ok & ema_long & rsi_long_ok,
            "enter_long"
        ] = 1

        # Short 진입
        dataframe.loc[
            short_breakout & swing_ok & atr_ok & adx_ok & vol_ok & ema_short & rsi_short_ok,
            "enter_short"
        ] = 1

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """청산 시그널 - ATR 기반 TP/SL은 custom_stoploss에서 처리."""
        # 기본 exit signal은 비활성
        dataframe["exit_long"] = 0
        dataframe["exit_short"] = 0
        return dataframe

    def custom_stoploss(self, pair: str, trade, current_time, current_rate,
                        current_profit, after_fill=False, **kwargs) -> float:
        """ATR 기반 동적 스탑로스."""
        dataframe, _ = self.dp.get_analyzed_pair_dataframe(pair, self.timeframe)
        if dataframe.empty:
            return self.stoploss

        last_candle = dataframe.iloc[-1]
        atr = last_candle.get("atr14", 0)
        if atr <= 0:
            return self.stoploss

        sl_dist = atr * self.atr_sl_mult.value
        sl_pct = sl_dist / current_rate

        return -sl_pct

    def custom_exit(self, pair: str, trade, current_time, current_rate,
                    current_profit, **kwargs):
        """ATR 기반 테이크프로핏."""
        dataframe, _ = self.dp.get_analyzed_pair_dataframe(pair, self.timeframe)
        if dataframe.empty:
            return None

        last_candle = dataframe.iloc[-1]
        atr = last_candle.get("atr14", 0)
        if atr <= 0:
            return None

        tp_dist = atr * self.atr_tp_mult.value
        tp_pct = tp_dist / trade.open_rate

        if current_profit >= tp_pct:
            return f"atr_tp_{self.atr_tp_mult.value}x"

        return None
