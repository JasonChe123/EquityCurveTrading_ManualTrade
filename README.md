# Equity Curve Trading Manual Trade

A manual trading application for futures trading with Interactive Brokers (IB) and MetaTrader 5 (MT5) integration. Features equity curve tracking, automated bracket orders, and browser automation for Tradovate.com.

## Features

- **Dual Platform Support**: Execute trades on both Interactive Brokers and MetaTrader 5 simultaneously
- **Bracket Orders**: Automatic take profit and stop loss order placement
- **Equity Curve Tracking**: Real-time equity curve visualization with 38-period SMA
- **Demo Mode**: Test trading strategies without real money
- **Reverse Order Logic**: Automatically reverse MT5 orders based on equity curve position
- **Browser Automation**: Send keyboard shortcuts to Tradovate.com after MT5 orders
- **Trade Recording**: Comprehensive CSV-based trade record keeping
- **Real-time ATR**: Average True Range calculation for dynamic position sizing

## Requirements

- Python 3.8+
- Interactive Brokers TWS or Gateway
- MetaTrader 5 (optional)
- pywinauto (for browser automation)

## Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd EquityCurveTrading_ManualTrade
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Configure Interactive Brokers:
   - Open TWS/Gateway
   - Enable ActiveX/Socket clients
   - Configure API port (default: 7496 for paper trading, 7497 for live)
   - Set trusted IPs

4. Configure MetaTrader 5 (optional):
   - Enable "Allow algorithmic trading"
   - Enable "Allow trading via API"

## Usage

### Basic Usage

Run the application:
```bash
python main.py
```

### Command Line Arguments

```bash
python main.py --host 192.168.1.104 --port 7496 --client-id 9999 --symbol NQ
```

Available arguments:
- `--host`: IB TWS/Gateway host (default: 192.168.1.104)
- `--port`: IB API port (default: 7496)
- `--client-id`: IB client ID (default: 9999)
- `--timeout`: Connection timeout in seconds (default: 10)
- `--symbol`: Trading symbol (default: NQ)
- `--exchange`: Exchange (default: CME)
- `--currency`: Currency (default: USD)
- `--sec-type`: Security type (default: FUT)
- `--expiry`: Contract expiry (default: auto-calculated front month)
- `--duration`: Historical data duration (default: 2 D)
- `--bar-size`: Bar size (default: 1 min)
- `--what-to-show`: Data type (default: TRADES)
- `--use-rth`: Regular trading hours only (default: 0)
- `--multiplier`: Contract multiplier (default: auto-detected)
- `--keep-up-to-date`: Keep historical data updated (default: True)

### Environment Variables

You can also configure using environment variables:
- `IB_HOST`
- `IB_PORT`
- `IB_CLIENT_ID`
- `IB_TIMEOUT`
- `IB_SYMBOL`
- `IB_EXCHANGE`
- `IB_CURRENCY`
- `IB_SEC_TYPE`
- `IB_EXPIRY`
- `IB_DURATION`
- `IB_BAR_SIZE`
- `IB_WHAT_TO_SHOW`
- `IB_USE_RTH`
- `IB_MULTIPLIER`
- `IB_KEEP_UP_TO_DATE`

## GUI Features

### Main Controls

- **Demo Trade**: Toggle between demo and live trading
- **IB Symbol**: Enter the futures symbol to trade
- **IB Qty**: Number of contracts
- **ATR Mult**: ATR multiplier for bracket distance calculation
- **MT5 Symbol**: MT5 symbol mapping (auto-mapped for NQ → NAS100_SB)
- **MT5 Contract Size**: Contract size for MT5 orders
- **Reverse Order**: Automatically reverse MT5 orders based on equity curve

### Order Buttons

- **Buy**: Place a buy bracket order
- **Sell**: Place a sell bracket order
- **Close All**: Close all open positions

### Trade Management

- **Open Positions Table**: View all open trades
- **Result Dropdown**: Select TP or SL to update trade results
- **Update Result**: Mark selected trades as closed with TP or SL
- **Show Equity Chart**: Display equity curve visualization

## Browser Automation

The application can automatically send keyboard shortcuts to Tradovate.com after MT5 orders are placed.

### Supported Browsers

- Firefox (checked first)
- Chrome (checked second)

### Keyboard Shortcuts

The shortcuts are sent based on trade direction and reverse order setting:

| Trade Direction | Reverse Order | Shortcut |
|-----------------|----------------|----------|
| Buy             | Checked        | Ctrl+Alt+S |
| Buy             | Unchecked      | Ctrl+Alt+B |
| Sell            | Checked        | Ctrl+Alt+B |
| Sell            | Unchecked      | Ctrl+Alt+S |

### Requirements for Browser Automation

- Install pywinauto: `pip install pywinauto`
- Have Firefox or Chrome open with a Tradovate.com tab
- The browser must be the active window when orders are placed

## Trade Recording

Trades are recorded in CSV files in the `trade_record/` directory with the following columns:

- date
- create_time
- ticker
- open_price
- take_profit
- stoploss
- quantity
- result
- side
- multiplier
- bet
- commission
- profit_loss
- demo_value (cumulative P/L)
- 38_sma (38-period simple moving average)
- signal (1 if demo_value > 38_sma, else 0)
- is_trade (1 if previous signal was 1, else -1)
- equity_curve_trading_value
- drawdown
- remark

## Supported Symbols

The application supports the following futures symbols with auto-detected multipliers:

- NQ (E-mini Nasdaq-100) - Multiplier: 20
- MNQ (Micro E-mini Nasdaq-100) - Multiplier: 2
- ES (E-mini S&P 500) - Multiplier: 50
- MES (Micro E-mini S&P 500) - Multiplier: 5
- YM (Dow Jones Industrial Average) - Multiplier: 5
- MYM (Micro Dow Jones) - Multiplier: 0.5
- RTY (Russell 2000) - Multiplier: 50
- M2K (Micro Russell 2000) - Multiplier: 5

## Commission Schedule

Round-trip commissions per contract:

- YM, ES, NQ, RTY: $3.10
- MYM, MES, MNQ, M2K: $1.04

## Troubleshooting

### IB Connection Issues

- Ensure TWS/Gateway is running
- Check that API is enabled in TWS configuration
- Verify port number (7496 for paper trading, 7497 for live)
- Check firewall settings

### MT5 Connection Issues

- Ensure MT5 is running
- Enable "Allow algorithmic trading" in MT5 terminal
- Enable "Allow trading via API"
- Check that the symbol is available in MT5

### Browser Automation Issues

- Ensure pywinauto is installed
- Make sure Firefox or Chrome is running
- Have a Tradovate.com tab open
- Run the application as administrator if needed

### Chart Issues

- If chart lines drop to zero, ensure trade results are updated
- Newly opened trades won't appear on chart until results are recorded
- Close and reopen the chart window if data doesn't update

## License

This project is provided as-is for educational and trading purposes.

## Disclaimer

This software is for educational purposes only. Trading futures involves significant risk of loss and is not suitable for all investors. Past performance is not indicative of future results. Use at your own risk.
