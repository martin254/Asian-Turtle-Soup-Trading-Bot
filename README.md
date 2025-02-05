# Asian-Turtle-Soup-Trading-Bot
Algorithmic implementation of ICT (Inner Circle Trader) concepts for Forex day trading, designed for the QuantConnect platform.This bot focuses on Asian session range analysis, order block detection, and Turtle Soup entries with strict risk management.

🔍 Overview
This algorithm implements key ICT trading strategies:

Asian session range establishment (00:00-08:00 UTC)

Order block identification

Turtle Soup entries after range breaches

Multi-timeframe market structure analysis

1:2 risk-reward ratio with dynamic position sizing

Pair: EURUSD
Platform: QuantConnect
Primary Session Focus: London/NY Session overlap

🚀 Key Features
Multi-Timeframe Analysis
Combines 1-minute and 4-hour timeframes for optimal entry timing

Session-Based Trading
Implements specific logic for Asian/London/NY sessions

Order Block Detection
Identifies significant rejection zones using hourly candles

Risk Management

1% account risk per trade

Automatic stop-loss calculation

Position size optimization

Daily Auto-Reset
Clears session variables at midnight UTC

📊 Strategy Components
1. Asian Session Range
Tracks high/low between 00:00-08:00 UTC

Requires minimum 5 pip range

Sets foundation for daily bias

2. Turtle Soup Entries
Wait for Asian range breach (+/-1 pip)

Monitor for price rejection

Enter on confirmation during London/NY overlap

Stop-loss beyond breach point or ATR-based

3. Order Block Detection

