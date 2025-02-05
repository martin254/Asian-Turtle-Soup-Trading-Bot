from datetime import datetime, timedelta
from clr import AddReference
AddReference("System")
AddReference("QuantConnect.Algorithm")
AddReference("QuantConnect.Indicators")
AddReference("QuantConnect.Common")

from System import *
from QuantConnect import *
from QuantConnect.Algorithm import *
from QuantConnect.Indicators import *
from QuantConnect.Data.Market import TradeBar
import decimal
import math

class ICTDayTradingAlgorithm(QCAlgorithm):
    def Initialize(self):
        self.SetCash(100000)
        self.SetStartDate(2023, 1, 1)
        self.SetEndDate(2024, 6, 30)
        
        # Add different timeframes for market structure
        self.symbol = self.AddForex("EURUSD", Resolution.Minute, Market.Oanda).Symbol
        self.symbol_4h = self.AddForex("EURUSD", Resolution.Hour, Market.Oanda).Symbol
        
        # Trading parameters
        self.risk_percent = 0.01  # 1% risk per trade
        self.reward_ratio = 2     # 1:2 risk/reward ratio
        self.min_stop_distance = 0.0005  # 5 pips minimum stop
        self.max_pos_size = 100000  # Maximum position size
        
        # ICT concepts parameters
        self.breach_threshold = 0.0001  # 1 pip breach
        self.rejection_threshold = 0.00005  # 0.5 pip rejection
        self.max_breach_time = timedelta(minutes=30)
        self.max_rejection_wait = timedelta(minutes=15)
        self.orderblock_lookback = 20  # Bars to look back for order blocks
        
        # Session times (UTC)
        self.asian_session_start = 0
        self.asian_session_end = 8
        self.london_session_start = 7
        self.ny_session_start = 13
        
        # Market structure indicators
        self.ema200_1h = self.EMA("EURUSD", 200, Resolution.Hour)
        self.ema50_1h = self.EMA("EURUSD", 50, Resolution.Hour)
        self.atr = self.ATR("EURUSD", 14, Resolution.Hour)
        
        # Order blocks tracking
        self.bearish_ob = None
        self.bullish_ob = None
        self.ob_threshold = 0.0010  # 10 pips for order block significance
        
        # Market structure variables
        self.htf_trend = None
        self.ltf_trend = None
        self.recent_highs = []
        self.recent_lows = []
        self.max_structure_points = 5
        
        # Trading state
        self.asian_high = 0
        self.asian_low = float('inf')
        self.asian_range_set = False
        self.breach_start_time = None
        self.breach_start_price = None
        self.breach_direction = None
        self.rejection_start_time = None
        self.rejection_price = None
        self.trade_placed = False
        
        self.Schedule.On(self.DateRules.EveryDay(), 
                        self.TimeRules.At(0, 0), 
                        self.ResetDailyVariables)

    def OnData(self, data):
        if not self.symbol in data or not self.ema200_1h.IsReady:
            return

        # Update market structure
        self.UpdateMarketStructure(data)
        
        # Update order blocks
        if self.Time.minute == 0:  # Update order blocks hourly
            self.UpdateOrderBlocks(data)

        current_hour = self.Time.hour
        current_price = data[self.symbol].Close

        if not self.asian_range_set:
            self.HandleAsianSession(current_hour, current_price)
        else:
            self.HandleTurtleSoup(current_hour, current_price, data)

    # NEW METHOD ADDED TO FIX ERROR
    def HandleAsianSession(self, current_hour, current_price):
        """Tracks Asian session price range (00:00-08:00 UTC)"""
        if current_hour < self.asian_session_end:
            # Update session high/low
            self.asian_high = max(self.asian_high, current_price)
            self.asian_low = min(self.asian_low, current_price)
            self.Debug(f"Asian session update - High: {self.asian_high}, Low: {self.asian_low}")
        else:
            # Finalize Asian session range
            self.asian_range_set = True
            self.Debug(f"Final Asian Range - High: {self.asian_high}, Low: {self.asian_low}")

    def UpdateMarketStructure(self, data):
        current_price = data[self.symbol].Close
        
        # Higher timeframe trend
        if self.ema200_1h.IsReady and self.ema50_1h.IsReady:
            if self.ema50_1h.Current.Value > self.ema200_1h.Current.Value:
                self.htf_trend = 'bullish'
            else:
                self.htf_trend = 'bearish'
        
        # Track recent swing points
        if len(self.recent_highs) > 0:
            if current_price > max(self.recent_highs):
                self.recent_highs.append(current_price)
                if len(self.recent_highs) > self.max_structure_points:
                    self.recent_highs.pop(0)
                self.ltf_trend = 'bullish'
        
        if len(self.recent_lows) > 0:
            if current_price < min(self.recent_lows):
                self.recent_lows.append(current_price)
                if len(self.recent_lows) > self.max_structure_points:
                    self.recent_lows.pop(0)
                self.ltf_trend = 'bearish'

    def UpdateOrderBlocks(self, data):
        if not data.ContainsKey(self.symbol): return
        
        current_price = data[self.symbol].Close
        candle_height = data[self.symbol].High - data[self.symbol].Low
        
        # Identify bullish order block (strong rejection of lows)
        if candle_height > self.ob_threshold and \
           data[self.symbol].Close > data[self.symbol].Open and \
           (self.bullish_ob is None or current_price < self.bullish_ob):
            self.bullish_ob = data[self.symbol].Low
            
        # Identify bearish order block (strong rejection of highs)
        if candle_height > self.ob_threshold and \
           data[self.symbol].Close < data[self.symbol].Open and \
           (self.bearish_ob is None or current_price > self.bearish_ob):
            self.bearish_ob = data[self.symbol].High

    def HandleTurtleSoup(self, current_hour, current_price, data):
        if self.breach_start_time is None:
            self.CheckForBreach(current_price)
        elif self.rejection_start_time is None:
            self.CheckForRejection(current_price)
        elif not self.trade_placed and current_hour >= self.ny_session_start:
            self.CheckForEntry(current_price, data)

    def CheckForBreach(self, current_price):
        if current_price > self.asian_high + self.breach_threshold:
            self.breach_start_time = self.Time
            self.breach_start_price = current_price
            self.breach_direction = 'high'
            self.Debug(f"High breach detected at {current_price}")
        elif current_price < self.asian_low - self.breach_threshold:
            self.breach_start_time = self.Time
            self.breach_start_price = current_price
            self.breach_direction = 'low'
            self.Debug(f"Low breach detected at {current_price}")

    def CheckForRejection(self, current_price):
        breach_time_elapsed = self.Time - self.breach_start_time
        
        if breach_time_elapsed > self.max_breach_time:
            self.Debug("Breach took too long, resetting")
            self.breach_start_time = None
            return
            
        if self.breach_direction == 'high' and current_price < self.asian_high:
            self.rejection_start_time = self.Time
            self.rejection_price = current_price
        elif self.breach_direction == 'low' and current_price > self.asian_low:
            self.rejection_start_time = self.Time
            self.rejection_price = current_price

    def CheckForEntry(self, current_price, data):
        if not self.ValidateTradeSetup(current_price):
            return
            
        account_value = self.Portfolio.TotalPortfolioValue
        risk_amount = account_value * self.risk_percent
        
        try:
            if self.breach_direction == 'high' and self.htf_trend == 'bearish':
                self.PlaceShortTrade(current_price, risk_amount)
            elif self.breach_direction == 'low' and self.htf_trend == 'bullish':
                self.PlaceLongTrade(current_price, risk_amount)
                
        except Exception as e:
            self.Debug(f"Error placing trade: {str(e)}")

    def ValidateTradeSetup(self, current_price):
        if self.Portfolio[self.symbol].Invested:
            return False
            
        # Check alignment with HTF trend
        if self.breach_direction == 'high' and self.htf_trend != 'bearish':
            return False
        if self.breach_direction == 'low' and self.htf_trend != 'bullish':
            return False
            
        # Check order block alignment
        if self.breach_direction == 'high' and self.bearish_ob:
            if current_price > self.bearish_ob:
                return False
        if self.breach_direction == 'low' and self.bullish_ob:
            if current_price < self.bullish_ob:
                return False
                
        return True

    def PlaceLongTrade(self, current_price, risk_amount):
        stop_loss = min(self.breach_start_price - self.min_stop_distance, 
                       current_price - self.atr.Current.Value)
        position_size = self.CalculatePositionSize(risk_amount, current_price, stop_loss)
        
        if position_size > 0:
            position_size = min(position_size, self.max_pos_size)
            take_profit = current_price + (current_price - stop_loss) * self.reward_ratio
            
            self.MarketOrder(self.symbol, position_size)
            self.StopMarketOrder(self.symbol, -position_size, stop_loss)
            self.LimitOrder(self.symbol, -position_size, take_profit)
            self.trade_placed = True

    def PlaceShortTrade(self, current_price, risk_amount):
        stop_loss = max(self.breach_start_price + self.min_stop_distance,
                       current_price + self.atr.Current.Value)
        position_size = self.CalculatePositionSize(risk_amount, current_price, stop_loss)
        
        if position_size > 0:
            position_size = min(position_size, self.max_pos_size)
            take_profit = current_price - (stop_loss - current_price) * self.reward_ratio
            
            self.MarketOrder(self.symbol, -position_size)
            self.StopMarketOrder(self.symbol, position_size, stop_loss)
            self.LimitOrder(self.symbol, position_size, take_profit)
            self.trade_placed = True

    def CalculatePositionSize(self, risk_amount, entry, stop_loss):
        pip_value = 0.0001
        pips_risked = abs(entry - stop_loss) / pip_value
        
        if pips_risked <= 0:
            return 0
            
        # Calculate standard lot size based on risk
        position_size = (risk_amount / pips_risked) / pip_value
        
        # Round down to 2 decimal places for micro lots
        position_size = math.floor(position_size * 100) / 100
        
        return position_size

    def ResetDailyVariables(self):
        """Resets daily trading variables at midnight UTC"""
        self.asian_high = 0
        self.asian_low = float('inf')
        self.asian_range_set = False
        self.breach_start_time = None
        self.breach_start_price = None
        self.breach_direction = None
        self.rejection_start_time = None
        self.rejection_price = None
        self.trade_placed = False
        self.Debug(f"{self.Time} - Daily variables reset")