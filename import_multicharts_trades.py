import csv
import os
from datetime import datetime

def get_commission(ticker: str) -> float:
    """Get round-trip commission for the given ticker."""
    commission_map = {
        "mnq": 1.24,
        "MNQ": 1.24,
        "nq": 2.48,
        "NQ": 2.48,
    }
    return commission_map.get(ticker, 0.0)

def get_multiplier(ticker: str) -> int:
    """Get multiplier for the given ticker."""
    multiplier_map = {
        "mnq": 2,
        "MNQ": 2,
        "nq": 20,
        "NQ": 20,
        "es": 50,
        "ES": 50,
        "mes": 5,
        "MES": 5,
        "ym": 5,
        "YM": 5,
        "mym": 0.5,
        "MYM": 0.5,
        "rty": 50,
        "RTY": 50,
        "m2k": 5,
        "M2K": 5,
    }
    return multiplier_map.get(ticker, 20)

def calculate_38_sma(values: list[float]) -> float:
    """Calculate 38-period simple moving average."""
    if len(values) < 38:
        return 0.0
    return sum(values[-38:]) / 38

def convert_date(date_str: str) -> str:
    """Convert DD/MM/YYYY to YYYY-MM-DD."""
    if not date_str:
        return datetime.now().strftime('%Y-%m-%d')
    parts = date_str.split('/')
    if len(parts) == 3:
        return f"{parts[2]}-{parts[1].zfill(2)}-{parts[0].zfill(2)}"
    return date_str

def determine_side(open_price: float, take_profit: float) -> str:
    """Determine trade side based on price movement."""
    if take_profit > open_price:
        return "BUY"
    else:
        return "SELL"

def import_multicharts_trades():
    """Import trades from MultiChartsTrades.csv to our trade record format."""
    input_file = "trade_record/MultiChartsTrades.csv"
    output_dir = "trade_record"
    os.makedirs(output_dir, exist_ok=True)
    
    # Use this year for the output file
    this_year = datetime.now().strftime('%Y')
    output_file = os.path.join(output_dir, f"trades_{this_year}.csv")
    
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
    
    # Read input CSV
    rows = []
    with open(input_file, 'r', newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Skip rows with missing essential data
            open_price_str = row.get('open price', '').strip()
            take_profit_str = row.get('take profit', '').strip()
            stoploss_str = row.get('stoploss', '').strip()
            
            if not open_price_str or not take_profit_str or not stoploss_str:
                continue
            
            # Convert date format
            date = convert_date(row.get('date', ''))
            create_time = row.get('create time', '') or "00:00:00"
            ticker = row.get('ticker', '').upper()
            open_price = float(open_price_str)
            take_profit = float(take_profit_str)
            stoploss = float(stoploss_str)
            quantity = int(row.get('quantity', 1))
            result = row.get('result', '').upper()
            
            # Determine side
            side = determine_side(open_price, take_profit)
            
            # Get multiplier and commission
            multiplier = get_multiplier(ticker)
            commission = get_commission(ticker)
            
            # Calculate bet
            tp_distance = abs(take_profit - open_price)
            sl_distance = abs(stoploss - open_price)
            bet = max(tp_distance, sl_distance) * quantity * multiplier
            
            # Calculate profit_loss
            if result == "TP":
                exit_price = take_profit
            else:  # SL
                exit_price = stoploss
            
            if side == "BUY":
                gross_profit = (exit_price - open_price) * quantity * multiplier
            else:  # SELL
                gross_profit = (open_price - exit_price) * quantity * multiplier
            
            profit_loss = gross_profit - commission
            
            rows.append({
                "date": date,
                "create_time": create_time,
                "ticker": ticker,
                "open_price": round(open_price, 2),
                "take_profit": round(take_profit, 2),
                "stoploss": round(stoploss, 2),
                "quantity": quantity,
                "result": result,
                "side": side,
                "multiplier": multiplier,
                "bet": round(bet, 2),
                "commission": round(commission, 2),
                "profit_loss": round(profit_loss, 2),
                "demo_value": 0.0,  # Will calculate later
                "38_sma": 0.0,  # Will calculate later
                "signal": 0,  # Will calculate later
                "is_trade": -1,  # Will calculate later
                "equity_curve_trading_value": 0.0,  # Will calculate later
                "drawdown": "",
                "remark": "Imported from MultiCharts"
            })
    
    # Calculate cumulative demo_value
    cumulative = 0.0
    demo_values = []
    for row in rows:
        cumulative += row['profit_loss']
        row['demo_value'] = round(cumulative, 2)
        demo_values.append(cumulative)
    
    # Calculate 38_sma for each row
    for i, row in enumerate(rows):
        if i >= 37:
            row['38_sma'] = round(calculate_38_sma(demo_values[:i+1]), 2)
    
    # Calculate signal and is_trade
    signals = []
    for i, row in enumerate(rows):
        demo_value = row['demo_value']
        sma_38 = row['38_sma']
        
        signal = 1 if demo_value > sma_38 else 0
        row['signal'] = signal
        signals.append(signal)
        
        if i == 0:
            is_trade = -1
        else:
            is_trade = 1 if signals[i-1] == 1 else -1
        row['is_trade'] = is_trade
    
    # Calculate equity_curve_trading_value
    equity_curve_value = 0.0
    for i, row in enumerate(rows):
        is_trade = row['is_trade']
        profit_loss = row['profit_loss']
        commission = row['commission']
        
        if i == 0:
            equity_curve_trading_value = 0.0
        else:
            if is_trade == 1:
                equity_curve_trading_value = equity_curve_value + profit_loss
            else:  # is_trade == -1
                equity_curve_trading_value = equity_curve_value - profit_loss - (2 * commission)
        equity_curve_value = equity_curve_trading_value
        row['equity_curve_trading_value'] = round(equity_curve_trading_value, 2)
    
    # Write to output CSV
    with open(output_file, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)
    
    print(f"Imported {len(rows)} trades from {input_file}")
    print(f"Output saved to {output_file}")
    print(f"Final cumulative P/L: ${cumulative:.2f}")
    print(f"Final 38 SMA: ${rows[-1]['38_sma']:.2f}")

if __name__ == "__main__":
    import_multicharts_trades()
