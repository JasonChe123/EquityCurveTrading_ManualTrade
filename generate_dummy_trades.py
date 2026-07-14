import csv
import os
from datetime import datetime, timedelta

def generate_dummy_trades():
    """Generate 40 dummy trades for testing 38_sma calculation."""
    trade_record_dir = "trade_record"
    os.makedirs(trade_record_dir, exist_ok=True)
    
    # Use today's date for the file
    today = datetime.now().strftime('%Y%m%d')
    trade_record_file = os.path.join(trade_record_dir, f"trades_{today}.csv")
    
    headers = [
        "date",
        "create_time",
        "ticker",
        "open_price",
        "take_profit",
        "stoploss",
        "quantity",
        "result",
        "side",
        "multiplier",
        "bet",
        "commission",
        "profit_loss",
        "demo_value",
        "38_sma",
        "signal",
        "is_trade",
        "equity_curve_trading_value",
        "drawdown",
        "remark"
    ]
    
    # Generate 40 trades with alternating results
    rows = []
    base_time = datetime.now().replace(hour=9, minute=0, second=0, microsecond=0)
    
    cumulative_pl = 0.0
    demo_values = []
    signals = []
    equity_curve_value = 0.0
    
    for i in range(40):
        # Alternate between BUY and SELL
        side = "BUY" if i % 2 == 0 else "SELL"
        
        # Alternate between TP and SL results (70% TP, 30% SL)
        result = "TP" if i % 10 < 7 else "SL"
        
        # Generate realistic prices
        base_price = 15000.0 + (i * 10)  # Slightly increasing trend
        open_price = base_price
        tp_distance = 25.75
        sl_distance = 25.75
        
        if side == "BUY":
            take_profit = open_price + tp_distance
            stoploss = open_price - sl_distance
            exit_price = take_profit if result == "TP" else stoploss
            gross_profit = (exit_price - open_price) * 1 * 20
        else:
            take_profit = open_price - tp_distance
            stoploss = open_price + sl_distance
            exit_price = take_profit if result == "TP" else stoploss
            gross_profit = (open_price - exit_price) * 1 * 20
        
        commission = 2.48  # NQ commission
        profit_loss = gross_profit - commission
        
        cumulative_pl += profit_loss
        demo_values.append(cumulative_pl)
        
        # Calculate 38_sma
        sma_38 = 0.0
        if i >= 37:
            sma_38 = sum(demo_values[-38:]) / 38
        
        # Calculate signal: 1 if demo_value > 38_sma, else 0
        signal = 1 if cumulative_pl > sma_38 else 0
        signals.append(signal)
        
        # Calculate is_trade: 1 if previous signal is 1, else -1
        if i == 0:
            is_trade = -1  # No previous signal for first row
        else:
            is_trade = 1 if signals[i-1] == 1 else -1
        
        # Calculate equity_curve_trading_value
        if i == 0:
            equity_curve_trading_value = 0.0  # First row starts at 0
        else:
            if is_trade == 1:
                equity_curve_trading_value = equity_curve_value + profit_loss
            else:  # is_trade == -1
                equity_curve_trading_value = equity_curve_value - (2 * commission)
        equity_curve_value = equity_curve_trading_value
        
        create_time = (base_time + timedelta(minutes=i*5)).strftime('%H:%M:%S')
        
        row = {
            "date": datetime.now().strftime('%Y-%m-%d'),
            "create_time": create_time,
            "ticker": "NQ",
            "open_price": round(open_price, 2),
            "take_profit": round(take_profit, 2),
            "stoploss": round(stoploss, 2),
            "quantity": 1,
            "result": result,
            "side": side,
            "multiplier": 20,
            "bet": round(tp_distance * 1 * 20, 2),
            "commission": round(commission, 2),
            "profit_loss": round(profit_loss, 2),
            "demo_value": round(cumulative_pl, 2),
            "38_sma": round(sma_38, 2),
            "signal": signal,
            "is_trade": is_trade,
            "equity_curve_trading_value": round(equity_curve_trading_value, 2),
            "drawdown": "",
            "remark": "Dummy trade for testing"
        }
        rows.append(row)
    
    # Write to CSV
    with open(trade_record_file, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)
    
    print(f"Generated 40 dummy trades in {trade_record_file}")
    print(f"Final cumulative P/L: ${cumulative_pl:.2f}")
    print(f"Final 38 SMA: ${sma_38:.2f}")

if __name__ == "__main__":
    generate_dummy_trades()
