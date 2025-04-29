from datetime import timedelta
from collections import deque
from clr import AddReference
AddReference("System")
AddReference("QuantConnect.Algorithm")
AddReference("QuantConnect.Indicators")
AddReference("QuantConnect.Common")

from QuantConnect import Resolution, Market
from QuantConnect.Algorithm import QCAlgorithm
from QuantConnect.Data.Market import TradeBar

class ICTDayTradingAlgorithm(QCAlgorithm):
    def Initialize(self):
        self.SetCash(100_000)
        self.SetStartDate(2023, 1, 1)
        self.SetEndDate(2024, 6, 30)

        # subscribe once, then consolidate
        self.symbol = self.AddForex("EURUSD", Resolution.Minute, Market.Oanda).Symbol

        # consolidate to 1h & 4h bars
        self.hour_bar = None
        self.window_4h = deque(maxlen=20)
        self.Consolidate(self.symbol, Resolution.Hour, self.OnHourBar)
        self.Consolidate(self.symbol, Resolution.Hour * 4, lambda bar: setattr(self, 'hour_bar', bar))

        # parameters
        self.risk_pct = 0.01
        self.rr = 2
        self.min_stop = 0.0005
        self.max_size = 100_000
        self.breach_thr = 0.0001
        self.ob_thr = 0.0010

        # sessions (UTC)
        self.sessions = dict(asian=(0, 8), london=(7, 13), ny=(13, 21))

        # indicators on 1h
        self.ema200 = self.EMA(self.symbol, 200, Resolution.Hour)
        self.ema50  = self.EMA(self.symbol,  50, Resolution.Hour)
        self.atr    = self.ATR(self.symbol,  14, Resolution.Hour)

        # state
        self.reset_daily()
        self.high_swings = deque(maxlen=5)
        self.low_swings  = deque(maxlen=5)

        self.Schedule.On(self.DateRules.EveryDay(),
                         self.TimeRules.At(0, 0),
                         lambda: self.reset_daily())

    def OnHourBar(self, bar: TradeBar):
        # maintain rolling 20 bars for orderblocks
        self.window_4h.append(bar)

    def OnData(self, data):
        # guard
        if not data.ContainsKey(self.symbol) or not self.ema200.IsReady: return

        price = data[self.symbol].Close
        now   = self.Time

        # build HTF trend
        htf = 'bullish' if self.ema50.Current.Value > self.ema200.Current.Value else 'bearish'

        # track swings
        if not self.high_swings or price > max(self.high_swings):
            self.high_swings.append(price)
        if not self.low_swings or price < min(self.low_swings):
            self.low_swings.append(price)

        # hourly OB only when we have ≥1 4h bar
        if self.window_4h:
            self.update_orderblocks(self.window_4h[-1])

        # session logic
        hour = now.hour
        if not self.asian_set:
            a_start, a_end = self.sessions['asian']
            if hour < a_end:
                self.asian_high = max(self.asian_high, price)
                self.asian_low  = min(self.asian_low,  price)
                return
            self.asian_set = True

        # state machine
        if not self.breach_time:
            if price > self.asian_high + self.breach_thr:
                self.breach_time, self.breach_price, self.dir = now, price, 'high'
            elif price < self.asian_low - self.breach_thr:
                self.breach_time, self.breach_price, self.dir = now, price, 'low'
            return

        # breach happened → wait for rejection
        if not self.reject_time:
            if self.dir == 'high' and price < self.asian_high:
                self.reject_time, self.reject_price = now, price
            elif self.dir == 'low'  and price > self.asian_low:
                self.reject_time, self.reject_price = now, price
            # timeout breach
            if now - self.breach_time > timedelta(minutes=30):
                self.breach_time = None
            return

        # rejection happened → enter only in NY session start
        if not self.trade and hour >= self.sessions['ny'][0]:
            if htf.startswith(self.dir == 'low' and 'bull' or 'bear'):
                self.enter_trade(price)
    
    def update_orderblocks(self, bar: TradeBar):
        rng = bar.High - bar.Low
        if rng < self.ob_thr: return
        if bar.Close > bar.Open and (not hasattr(self, 'bull_ob') or bar.Low < self.bull_ob):
            self.bull_ob = bar.Low
        if bar.Close < bar.Open and (not hasattr(self, 'bear_ob') or bar.High > self.bear_ob):
            self.bear_ob = bar.High

    def enter_trade(self, price):
        # no existing position
        if self.Portfolio[self.symbol].Invested: return

        # validate OB alignment
        if self.dir=='high' and getattr(self, 'bear_ob', float('inf')) < price: return
        if self.dir=='low'  and getattr(self, 'bull_ob',      0) > price: return

        # risk & size
        equity = self.Portfolio.TotalPortfolioValue
        risk_am = equity * self.risk_pct
        sl = (self.dir=='high'
              and min(self.breach_price - self.min_stop, price - self.atr.Current.Value)
              or max(self.breach_price + self.min_stop, price + self.atr.Current.Value))
        pips = abs(price - sl) / 0.0001
        size = min(self.max_size, math.floor((risk_am / pips) / 0.0001) / 100)

        if size <= 0: return

        tp = price + (price - sl) * (self.rr * (1 if self.dir=='low' else -1))
        qty = size * (1 if self.dir=='low' else -1)

        self.MarketOrder(self.symbol,     qty)
        self.StopMarketOrder(self.symbol, -qty, sl)
        self.LimitOrder(self.symbol,     -qty, tp)
        self.trade = True

    def reset_daily(self):
        self.asian_high = 0
        self.asian_low  = float('inf')
        self.asian_set  = False
        self.breach_time = None
        self.reject_time = None
        self.trade      = False
