# Setup Guide

## Prerequisites

### Interactive Brokers Setup

1. **Install TWS or Gateway**
   - Download from https://www.interactivebrokers.com/en/trading/tws.php
   - For automated trading, Gateway is recommended (lighter weight)

2. **Configure API Access**
   - Open TWS/Gateway
   - Go to File → Global Configuration → API → Settings
   - Enable "ActiveX and Socket Clients"
   - Set "Socket Port" (7496 for paper trading, 7497 for live)
   - Uncheck "Read-Only API"
   - Add your IP address to "Trusted IPs" (or leave as 127.0.0.1 for local)

3. **Configure Account**
   - Ensure your account has trading permissions for futures
   - Check margin requirements for your intended symbols

### MetaTrader 5 Setup (Optional)

1. **Install MT5**
   - Download from https://www.metatrader5.com/en/download
   - Install and login to your broker account

2. **Enable Algorithmic Trading**
   - Open MT5 terminal
   - Go to Tools → Options → Expert Advisors
   - Check "Allow algorithmic trading"
   - Check "Allow trading via API"
   - Uncheck "Confirm trade execution" (optional, for faster execution)

3. **Configure Symbols**
   - Ensure your desired symbols are visible in Market Watch
   - Right-click symbol → Properties to verify contract specifications

### Browser Automation Setup

1. **Install pywinauto**
   ```bash
   pip install pywinauto
   ```

2. **Configure Browser**
   - Install Firefox or Chrome
   - Create a Tradovate.com account
   - Keep a tab open with Tradovate.com when trading

## Installation

### Python Environment

1. **Install Python 3.8+**
   - Download from https://www.python.org/downloads/
   - During installation, check "Add Python to PATH"

2. **Create Virtual Environment (Recommended)**
   ```bash
   python -m venv venv
   # Windows
   venv\Scripts\activate
   # Linux/Mac
   source venv/bin/activate
   ```

3. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   ```

## Configuration

### Environment Variables (Optional)

Create a `.env` file or set system environment variables:

```bash
# IB Connection
IB_HOST=192.168.1.104
IB_PORT=7496
IB_CLIENT_ID=9999
IB_TIMEOUT=10

# Trading Parameters
IB_SYMBOL=NQ
IB_EXCHANGE=CME
IB_CURRENCY=USD
IB_SEC_TYPE=FUT
IB_DURATION=2 D
IB_BAR_SIZE=1 min
IB_WHAT_TO_SHOW=TRADES
IB_USE_RTH=0
IB_KEEP_UP_TO_DATE=1
```

### Command Line Arguments

You can override settings via command line:

```bash
python main.py --symbol ES --port 7497 --client-id 1000
```

## Running the Application

### Basic Start

```bash
python main.py
```

### With Custom Settings

```bash
python main.py --host 127.0.0.1 --port 7496 --symbol MNQ
```

### Paper Trading vs Live Trading

- **Paper Trading**: Use port 7496
- **Live Trading**: Use port 7497

## First Run Checklist

- [ ] IB TWS/Gateway is running
- [ ] API is enabled in TWS/Gateway
- [ ] Correct port is configured (7496 for paper, 7497 for live)
- [ ] MT5 is running (if using MT5)
- [ ] Algorithmic trading is enabled in MT5 (if using MT5)
- [ ] Browser is open with Tradovate.com tab (if using browser automation)
- [ ] Python dependencies are installed
- [ ] Account has sufficient margin for trading

## Troubleshooting Setup Issues

### IB Connection Fails

1. Check TWS/Gateway is running
2. Verify API is enabled
3. Confirm port number
4. Check firewall settings
5. Ensure IP is in trusted IPs list

### MT5 Connection Fails

1. Verify MT5 is running
2. Check algorithmic trading is enabled
3. Ensure symbol is available in MT5
4. Verify broker allows API trading

### Browser Automation Fails

1. Install pywinauto: `pip install pywinauto`
2. Run application as administrator
3. Ensure browser is running
4. Check Tradovate.com tab is open

### Import Errors

1. Ensure virtual environment is activated
2. Reinstall dependencies: `pip install -r requirements.txt`
3. Check Python version is 3.8+

## Security Considerations

- Never commit API credentials to version control
- Use paper trading account for testing
- Keep your .env file private
- Use strong passwords for trading accounts
- Enable two-factor authentication where available
