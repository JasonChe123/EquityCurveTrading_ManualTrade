import MetaTrader5 as mt5

def test_mt5_connection():
    """Test connection to MetaTrader 5 terminal."""
    
    # Initialize MT5
    if not mt5.initialize():
        print(f"MT5 initialize failed: {mt5.last_error()}")
        return False
    
    print("Connected to MetaTrader 5")
    
    # Get terminal info
    info = mt5.terminal_info()
    if info is not None:
        print(f"Terminal name: {info.name}")
        print(f"Terminal path: {info.path}")
        print(f"Company: {info.company}")
        # print(f"Account: {info.login}")
        print(f"Trade allowed: {info.trade_allowed}")
        print(f"Trade API disabled: {info.tradeapi_disabled}")
        print(f"Connected: {info.connected}")
    
    # Get account info
    account = mt5.account_info()
    if account is not None:
        print(f"Balance: {account.balance}")
        print(f"Equity: {account.equity}")
        print(f"Margin: {account.margin}")
        print(f"Free margin: {account.margin_free}")
    
    # Shutdown
    mt5.shutdown()
    print("MT5 connection closed")
    return True

if __name__ == "__main__":
    test_mt5_connection()
