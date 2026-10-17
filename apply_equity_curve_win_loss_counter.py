import csv
from typing import List, Dict

def calculate_5_sma(demo_values: List[float]) -> float:
    """Calculate 5-period simple moving average."""
    if len(demo_values) == 0:
        return 0.0
    return sum(demo_values[-5:]) / 5

def apply_equity_curve_logic(input_file: str, output_file: str) -> None:
    """Read backup CSV, apply equity curve trading logic, and save to output."""
    
    # Read the backup CSV
    with open(input_file, 'r', newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    
    
    # Calculate derived fields
    win_loss_count = 0.0  # This is the Signal (win/loss counter)
    cumulative_profit_loss = 0.0  # This is the Demo Value (cumulative profit/loss)
    signals = []
    
    # First pass: calculate demo_value (cumulative profit_loss), signal (win/loss counter), and 5_sma
    for i, row in enumerate(rows):
        # Demo Value = cumulative profit/loss
        profit_loss_str = row.get('profit_loss', '0')
        profit_loss = float(profit_loss_str) if profit_loss_str and str(profit_loss_str).strip() else 0.0
        cumulative_profit_loss += profit_loss
        row['demo_value'] = round(cumulative_profit_loss, 2)
        
        # Signal = win/loss counter (+1 for TP, -1 for SL)
        result = row.get('result', '')
        if isinstance(result, str):
            result = result.strip()
        if result:
            if result == 'TP':
                win_loss_count += 1
            elif result == 'SL':
                win_loss_count -= 1
        row['signal'] = round(win_loss_count, 2)
        signals.append(win_loss_count)
        
        # 5 SMA = 5-period simple moving average of Signal
        if i >= 4:  # Need at least 5 data points (0-indexed)
            sma_5 = calculate_5_sma(signals)
            row['5_sma'] = round(sma_5, 2)
        else:
            row['5_sma'] = ''
    
    # Second pass: calculate is_trade, equity_curve_trading_value, and drawdown
    equity_curve_value = 0.0
    peak_value = 0.0
    
    for i, row in enumerate(rows):
        # Calculate is_trade (1 if previous signal > 5_sma, -1 otherwise)
        if i == 0:
            is_trade = -1  # First trade is not taken
        else:
            prev_signal = signals[i-1]
            prev_5_sma_str = rows[i-1].get('5_sma', 0)
            prev_5_sma = float(prev_5_sma_str) if prev_5_sma_str and str(prev_5_sma_str).strip() else 0.0
            is_trade = 1 if prev_signal >= prev_5_sma else -1
        row['is_trade'] = is_trade
        
        # Calculate equity_curve_trading_value
        profit_loss_str = row.get('profit_loss', '0')
        profit_loss = float(profit_loss_str) if profit_loss_str and str(profit_loss_str).strip() else 0.0
        
        commission_str = row.get('commission', '0')
        commission = float(commission_str) if commission_str and str(commission_str).strip() else 0.0
        
        # Skip equity curve calculation for trades without 5_sma values (first 4 trades)
        sma_5_str = row.get('5_sma', '')
        if not sma_5_str or not str(sma_5_str).strip():
            equity_curve_trading_value = equity_curve_value  # No change, skip this trade
        else:
            if is_trade == 1:
                # Follow trade: add profit_loss
                equity_curve_trading_value = equity_curve_value + profit_loss
            else:  # is_trade == -1
                # Reverse trade: subtract profit_loss and 2*commission
                equity_curve_trading_value = equity_curve_value - profit_loss - (2 * commission)
        
        equity_curve_value = equity_curve_trading_value
        row['equity_curve_trading_value'] = round(equity_curve_trading_value, 2)
        
        # Calculate drawdown
        peak_value = max(peak_value, equity_curve_value)
        drawdown = equity_curve_value - peak_value
        row['drawdown'] = round(drawdown, 2)
    
    # Define output fieldnames (preserve original order + new fields)
    fieldnames = [
        'date', 'create_time', 'trade_number', 'ticker', 'open_price',
        'take_profit', 'stoploss', 'quantity', 'result', 'side', 'multiplier',
        'bet', 'commission', 'profit_loss', 'demo_value', 'remark',
        '5_sma', 'signal', 'is_trade', 'equity_curve_trading_value', 'drawdown'
    ]
    
    # Write to output file
    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    

if __name__ == '__main__':
    input_csv = 'trade_record/trades_backup.csv'
    output_csv = 'trade_record/trades_2026.csv'
    apply_equity_curve_logic(input_csv, output_csv)
