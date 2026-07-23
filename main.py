from __future__ import annotations

import argparse
import csv
import os
import threading
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import tkinter as tk
from tkinter import messagebox, ttk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import matplotlib.dates as mdates
import random
import time

try:
    import pywinauto
    from pywinauto.keyboard import send_keys
    PYWINAUTO_AVAILABLE = True
except ImportError:
    PYWINAUTO_AVAILABLE = False

from ibapi.contract import Contract
from ibapi.client import EClient
from ibapi.common import BarData
from ibapi.order import Order
from ibapi.wrapper import EWrapper

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None


@dataclass(frozen=True)
class IBConfig:
    host: str
    port: int
    client_id: int
    timeout: float
    symbol: str
    exchange: str
    currency: str
    sec_type: str
    expiry: str | None
    duration: str
    bar_size: str
    what_to_show: str
    use_rth: int
    keep_up_to_date: bool
    multiplier: str


class IBConnectionApp(EWrapper, EClient):
    def __init__(self) -> None:
        EClient.__init__(self, self)
        self.connected_event = threading.Event()
        self.contract_details_event = threading.Event()
        self.positions_event = threading.Event()
        self._next_valid_order_id: int | None = None
        self._bars: list[tuple[str, float, float, float, float]] = []
        self._positions: dict[str, float] = {}
        self._bracket_orders: dict[str, list[int]] = {}
        self._min_tick: float | None = None
        self._atr_period = 14
        self._last_atr = 0.0
        self._last_close = 0.0
        self._order_lock = threading.Lock()

    def nextValidId(self, orderId: int) -> None:
        self._next_valid_order_id = orderId
        self.connected_event.set()
        print(f"Connected. Next valid order id: {orderId}")

    def historicalData(self, reqId: int, bar: BarData) -> None:
        self._record_bar(reqId, bar, "Historical")

    def historicalDataUpdate(self, reqId: int, bar: BarData) -> None:
        self._record_bar(reqId, bar, "Update")

    def contractDetails(self, reqId, contractDetails) -> None:  # type: ignore[no-untyped-def]
        self._min_tick = float(contractDetails.minTick)
        print(f"Contract min tick for req {reqId}: {self._min_tick}")

    def contractDetailsEnd(self, reqId: int) -> None:
        self.contract_details_event.set()

    def position(self, account, contract, position, avgCost) -> None:  # type: ignore[no-untyped-def]
        self._positions[contract.symbol] = float(position)

    def positionEnd(self) -> None:
        self.positions_event.set()

    def _record_bar(self, reqId: int, bar: BarData, label: str) -> None:
        bar_date = str(bar.date)
        row = (bar_date, float(bar.open), float(bar.high), float(bar.low), float(bar.close))
        if self._bars and self._bars[-1][0] == bar_date:
            self._bars[-1] = row
        else:
            self._bars.append(row)

        atr = self._average_true_range()
        self._last_atr = atr
        self._last_close = row[4]
        # print(
        #     f"{label} {reqId}: {bar.date} O={bar.open} H={bar.high} "
        #     f"L={bar.low} C={bar.close} V={bar.volume} ATR({self._atr_period})={atr:.2f}"
        # )

    def _average_true_range(self) -> float:
        if len(self._bars) < 2:
            return 0.0

        true_ranges: list[float] = []
        previous_close = self._bars[0][4]
        for _, _, high, low, close in self._bars[1:]:
            true_range = max(
                high - low,
                abs(high - previous_close),
                abs(low - previous_close),
            )
            true_ranges.append(true_range)
            previous_close = close

        period = min(self._atr_period, len(true_ranges))
        atr = sum(true_ranges[:period]) / period
        for true_range in true_ranges[period:]:
            atr = ((atr * (self._atr_period - 1)) + true_range) / self._atr_period
        return atr

    def error(
        self,
        reqId: int,
        errorCode: int,
        errorString: str,
        advancedOrderRejectJson: str = "",
    ) -> None:
        print(f"IB error {errorCode} on req {reqId}: {errorString}")
        if errorCode == 200:
            print("Check the expiry month and exchange on the futures contract.")

    @property
    def next_valid_order_id(self) -> int | None:
        return self._next_valid_order_id

    @property
    def last_atr(self) -> float:
        return self._last_atr

    @property
    def last_close(self) -> float:
        return self._last_close

    @property
    def min_tick(self) -> float | None:
        return self._min_tick

    def request_contract_min_tick(self, req_id: int, contract: Contract, timeout: float) -> float:
        self._min_tick = None
        self.contract_details_event.clear()
        self.reqContractDetails(req_id, contract)
        if not self.contract_details_event.wait(timeout):
            raise TimeoutError("Timed out waiting for contract details")
        if self._min_tick is None or self._min_tick <= 0:
            raise RuntimeError("IB did not return a valid min tick")
        return self._min_tick

    def request_positions(self, timeout: float) -> None:
        self.positions_event.clear()
        self.reqPositions()
        self.positions_event.wait(timeout)

    def current_position(self, symbol: str) -> float:
        return self._positions.get(symbol, 0.0)

    def _register_bracket_orders(self, symbol: str, order_ids: list[int]) -> None:
        self._bracket_orders[symbol] = order_ids

    def _cancel_bracket_orders(self, symbol: str) -> None:
        order_ids = self._bracket_orders.pop(symbol, [])
        for order_id in order_ids:
            print(f"Cancelling bracket order {order_id} for {symbol}")
            self.cancelOrder(order_id)

    @staticmethod
    def _market_order(action: str, quantity: int) -> Order:
        order = Order()
        order.action = action
        order.orderType = "MKT"
        order.totalQuantity = quantity
        order.tif = "DAY"
        order.eTradeOnly = ""
        order.firmQuoteOnly = ""
        order.account = "U14659833"
        return order

    @staticmethod
    def _limit_order(action: str, quantity: int, limit_price: float) -> Order:
        order = Order()
        order.action = action
        order.orderType = "LMT"
        order.totalQuantity = quantity
        order.lmtPrice = limit_price
        order.tif = "DAY"
        order.eTradeOnly = ""
        order.firmQuoteOnly = ""
        order.account = "U14659833"
        return order

    @staticmethod
    def _stop_order(action: str, quantity: int, stop_price: float) -> Order:
        order = Order()
        order.action = action
        order.orderType = "STP"
        order.totalQuantity = quantity
        order.auxPrice = stop_price
        order.tif = "DAY"
        order.eTradeOnly = ""
        order.firmQuoteOnly = ""
        order.account = "U14659833"
        return order

    def place_market_order(self, contract: Contract, action: str, quantity: int) -> int:
        if self._next_valid_order_id is None:
            raise RuntimeError("No valid order id received from IB")
        if quantity <= 0:
            raise ValueError("Quantity must be positive")

        with self._order_lock:
            order_id = self._next_valid_order_id
            self._next_valid_order_id += 1

        order = self._market_order(action, quantity)
        print(f"Placing market order: {action} {quantity} {contract.symbol} (id {order_id})")
        self.placeOrder(order_id, contract, order)
        return order_id

    def place_bracket_market_order(
        self,
        contract: Contract,
        action: str,
        quantity: int,
        take_profit: float,
        stop_loss: float,
    ) -> int:
        if self._next_valid_order_id is None:
            raise RuntimeError("No valid order id received from IB")
        if quantity <= 0:
            raise ValueError("Quantity must be positive")

        with self._order_lock:
            parent_id = self._next_valid_order_id
            self._next_valid_order_id += 3

        parent = self._market_order(action, quantity)
        parent.orderId = parent_id
        parent.transmit = False

        opposite = "SELL" if action == "BUY" else "BUY"
        take_profit_order = self._limit_order(opposite, quantity, take_profit)
        take_profit_order.orderId = parent_id + 1
        take_profit_order.parentId = parent_id
        take_profit_order.transmit = False

        stop_loss_order = self._stop_order(opposite, quantity, stop_loss)
        stop_loss_order.orderId = parent_id + 2
        stop_loss_order.parentId = parent_id
        stop_loss_order.transmit = True

        print(
            f"Placing bracket order: {action} MKT, TP={take_profit:.2f}, "
            f"SL={stop_loss:.2f}, parent id {parent_id}"
        )
        self.placeOrder(parent_id, contract, parent)
        self.placeOrder(parent_id + 1, contract, take_profit_order)
        self.placeOrder(parent_id + 2, contract, stop_loss_order)
        self._register_bracket_orders(contract.symbol, [parent_id, parent_id + 1, parent_id + 2])
        return parent_id

    def close_position(self, contract: Contract) -> int:
        self._cancel_bracket_orders(contract.symbol)
        position = self.current_position(contract.symbol)
        if position == 0:
            raise RuntimeError(f"No open position found for {contract.symbol}")
        action = "SELL" if position > 0 else "BUY"
        return self.place_market_order(contract, action, int(abs(position)))


class MT5ConnectionApp:
    def __init__(self) -> None:
        self.available = mt5 is not None
        self.connected = False
        self._magic = 51001

    def connect(self) -> None:
        if not self.available:
            raise RuntimeError("MetaTrader5 package is not installed")
        if self.connected:
            return
        if not mt5.initialize():
            raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
        self.connected = True
        print("Connected to MetaTrader 5")
        info = mt5.terminal_info()
        if info is not None:
            trade_allowed = getattr(info, "trade_allowed", None)
            tradeapi_disabled = getattr(info, "tradeapi_disabled", None)
            print(
                f"MT5 terminal: trade_allowed={trade_allowed} tradeapi_disabled={tradeapi_disabled}"
            )
            if trade_allowed is False or tradeapi_disabled is True:
                raise RuntimeError(
                    "MT5 terminal is not allowing trading. Enable algorithmic trading / trading permission in the terminal."
                )

    def terminal_status(self) -> object | None:
        if not self.connected:
            return None
        return mt5.terminal_info()

    def shutdown(self) -> None:
        if self.available and self.connected:
            mt5.shutdown()
            self.connected = False

    def _ensure_symbol(self, symbol: str) -> None:
        info = mt5.symbol_info(symbol)
        if info is None:
            raise RuntimeError(f"MT5 symbol not found: {symbol}")
        if not info.visible:
            if not mt5.symbol_select(symbol, True):
                raise RuntimeError(f"MT5 could not select symbol: {symbol}")

    def _market_price(self, symbol: str, action: str) -> float:
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            raise RuntimeError(f"MT5 tick not available for {symbol}")
        price = tick.ask if action == "BUY" else tick.bid
        if price <= 0:
            raise RuntimeError(f"MT5 invalid market price for {symbol}")
        return float(price)

    def place_bracket_market_order(
        self,
        symbol: str,
        action: str,
        volume: float,
        contract_size: float,
        tp_points: float,
        sl_points: float,
    ) -> int:
        if not self.connected:
            raise RuntimeError("MT5 is not connected")
        if volume <= 0:
            raise ValueError("Quantity must be positive")
        if contract_size <= 0:
            raise ValueError("MT5 contract size must be positive")
        if tp_points <= 0 or sl_points <= 0:
            raise ValueError("TP/SL points must be positive")

        self._ensure_symbol(symbol)
        volume = float(volume) * float(contract_size)
        price = self._market_price(symbol, action)
        if action == "BUY":
            tp = price + tp_points
            sl = price - sl_points
            order_type = mt5.ORDER_TYPE_BUY
        else:
            tp = price - tp_points
            sl = price + sl_points
            order_type = mt5.ORDER_TYPE_SELL

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": float(volume),
            "type": order_type,
            "price": price,
            "sl": sl,
            "tp": tp,
            "deviation": 20,
            "magic": self._magic,
            "comment": "IB-equivalent bracket",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(request)
        if result is None:
            raise RuntimeError("MT5 order_send returned None")
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            raise RuntimeError(f"MT5 order failed: retcode={result.retcode}, comment={result.comment}")
        print(f"Placing MT5 bracket order: {action} {symbol} volume={volume} TP={tp:.5f} SL={sl:.5f}")
        return int(result.order)

    def close_position(self, symbol: str) -> int:
        if not self.connected:
            raise RuntimeError("MT5 is not connected")
        self._ensure_symbol(symbol)

        positions = mt5.positions_get(symbol=symbol)
        if not positions:
            raise RuntimeError(f"No MT5 open position found for {symbol}")

        last_order = 0
        for position in positions:
            tick = mt5.symbol_info_tick(symbol)
            if tick is None:
                raise RuntimeError(f"MT5 tick not available for {symbol}")
            if position.type == mt5.POSITION_TYPE_BUY:
                order_type = mt5.ORDER_TYPE_SELL
                price = tick.bid
            else:
                order_type = mt5.ORDER_TYPE_BUY
                price = tick.ask

            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": float(position.volume),
                "type": order_type,
                "position": position.ticket,
                "price": float(price),
                "deviation": 20,
                "magic": self._magic,
                "comment": "Close position",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }
            result = mt5.order_send(request)
            if result is None:
                raise RuntimeError("MT5 close order returned None")
            if result.retcode != mt5.TRADE_RETCODE_DONE:
                raise RuntimeError(f"MT5 close failed: retcode={result.retcode}, comment={result.comment}")
            last_order = int(result.order)

        return last_order


def load_config() -> IBConfig:
    parser = argparse.ArgumentParser(
        description="Request NQ 1-minute historical bars from Interactive Brokers using ibapi."
    )
    parser.add_argument("--host", default=os.getenv("IB_HOST", "192.168.1.104"))
    parser.add_argument("--port", type=int, default=int(os.getenv("IB_PORT", "7496")))
    parser.add_argument("--client-id", type=int, default=int(os.getenv("IB_CLIENT_ID", "9999")))
    parser.add_argument("--timeout", type=float, default=float(os.getenv("IB_TIMEOUT", "10")))
    parser.add_argument("--symbol", default=os.getenv("IB_SYMBOL", "MNQ"))
    parser.add_argument("--exchange", default=os.getenv("IB_EXCHANGE", "CME"))
    parser.add_argument("--currency", default=os.getenv("IB_CURRENCY", "USD"))
    parser.add_argument("--sec-type", default=os.getenv("IB_SEC_TYPE", "FUT"))
    parser.add_argument("--expiry", default=os.getenv("IB_EXPIRY"))
    parser.add_argument("--duration", default=os.getenv("IB_DURATION", "2 D"))
    parser.add_argument("--bar-size", default=os.getenv("IB_BAR_SIZE", "1 min"))
    parser.add_argument("--what-to-show", default=os.getenv("IB_WHAT_TO_SHOW", "TRADES"))
    parser.add_argument("--use-rth", type=int, default=int(os.getenv("IB_USE_RTH", "0")))
    parser.add_argument("--multiplier", default=os.getenv("IB_MULTIPLIER", "20"))
    parser.add_argument(
        "--keep-up-to-date",
        action=argparse.BooleanOptionalAction,
        default=os.getenv("IB_KEEP_UP_TO_DATE", "1") != "0",
    )
    args, _ = parser.parse_known_args()
    return IBConfig(
        host=args.host,
        port=args.port,
        client_id=args.client_id,
        timeout=args.timeout,
        symbol=args.symbol,
        exchange=args.exchange,
        currency=args.currency,
        sec_type=args.sec_type,
        expiry=args.expiry,
        duration=args.duration,
        bar_size=args.bar_size,
        what_to_show=args.what_to_show,
        use_rth=args.use_rth,
        keep_up_to_date=args.keep_up_to_date,
        multiplier=args.multiplier,
    )


def third_friday(year: int, month: int) -> date:
    first_day = date(year, month, 1)
    first_friday_offset = (4 - first_day.weekday()) % 7
    return date(year, month, 1 + first_friday_offset + 14)


def front_month_expiry(today: date | None = None) -> str:
    today = today or date.today()
    roll_cutoff = timedelta(days=2)
    for year in (today.year, today.year + 1):
        for month in (3, 6, 9, 12):
            if year == today.year and month < today.month:
                continue
            expiry_date = third_friday(year, month)
            if today <= expiry_date - roll_cutoff:
                return f"{year}{month:02d}"
    return f"{today.year + 1}03"


def get_multiplier_for_symbol(symbol: str) -> str:
    """Get the correct multiplier for a given futures symbol."""
    multiplier_map = {
        "NQ": "20",
        "MNQ": "2",
        "ES": "50",
        "MES": "5",
        "YM": "5",
        "MYM": "0.5",
        "RTY": "50",
        "M2K": "5",
    }
    return multiplier_map.get(symbol.upper(), "20")


def build_contract(config: IBConfig, symbol: str) -> Contract:
    contract = Contract()
    contract.symbol = symbol
    contract.secType = "FUT"
    contract.exchange = config.exchange
    contract.currency = config.currency
    contract.multiplier = get_multiplier_for_symbol(symbol)
    contract.tradingClass = symbol
    contract.lastTradeDateOrContractMonth = config.expiry or front_month_expiry()
    contract.includeExpired = False
    return contract


class TradingGUI:
    def __init__(self, root: tk.Tk, config: IBConfig) -> None:
        self.root = root
        self.config = config
        self.app = IBConnectionApp()
        self.mt5_app = MT5ConnectionApp()
        self.contract = build_contract(config, config.symbol)

        self.symbol_var = tk.StringVar(value=config.symbol)
        if config.symbol in ('NQ', 'nq','MNQ', 'mnq'):
            self.mt5_symbol_var = tk.StringVar(value="NAS100_SB")
        else:
            self.mt5_symbol_var = tk.StringVar(value=config.symbol)
        self.qty_var = tk.StringVar(value="1")
        self.mt5_contract_size_var = tk.StringVar(value="0.1")
        self.atr_var = tk.StringVar(value="10")
        self.reverse_order_var = tk.BooleanVar(value=False)
        self.ib_send_var = tk.BooleanVar(value=False)
        self.mt5_send_var = tk.BooleanVar(value=False)
        self.tradovate_send_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="Connecting...")
        self.demo_status_var = tk.StringVar(value="")
        self.atr_display_var = tk.StringVar(value="ATR: --")
        self.open_positions = []
        self.position_dropdown_vars = {}
        self.browser_app = None
        self.browser_window = None
        self.browser_connected = False
        self.browser_name = ""
        self._browser_check_counter = 0
        self.reconnect_browser_button = None
        self._startup_time = datetime.now()
        self._allow_auto_update = False
        self._cached_contract = None
        self._cached_min_tick = None
        self._cached_tradovate_tab = None

        self._init_trade_record()
        self._init_chart()

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._connect_and_load()
        self._load_open_positions()
        self._update_reverse_order_checkbox()
        self._poll_status()

    def _build_ui(self) -> None:
        self.root.title("IB Trader")
        self.root.resizable(False, False)
        self.root.attributes('-topmost', True)

        main = ttk.Frame(self.root, padding=12)
        main.grid(row=0, column=0, sticky="nsew")

        ttk.Checkbutton(main, text="Reverse Order", variable=self.reverse_order_var).grid(row=0, column=0, sticky="w")
        ttk.Label(main, text="ATR Mult").grid(row=0, column=1, sticky="w")
        ttk.Entry(main, textvariable=self.atr_var, width=12).grid(row=0, column=2, sticky="w")

        ttk.Checkbutton(main, text="Send to IB", variable=self.ib_send_var).grid(row=1, column=0, sticky="w")
        ttk.Label(main, text="IB Symbol", width=8).grid(row=1, column=1, sticky="w")
        symbol_entry = ttk.Entry(main, textvariable=self.symbol_var, width=12)
        symbol_entry.grid(row=1, column=2, sticky="w")
        symbol_entry.bind('<Return>', lambda e: self._refresh_symbol_data())
        ttk.Label(main, text="IB Qty").grid(row=1, column=3, sticky="w")
        ttk.Entry(main, textvariable=self.qty_var, width=12).grid(row=1, column=4, sticky="w")

        ttk.Checkbutton(main, text="Send to MT5", variable=self.mt5_send_var).grid(row=2, column=0, sticky="w")
        ttk.Label(main, text="MT5 Symbol", width=8).grid(row=2, column=1, sticky="w")
        ttk.Entry(main, textvariable=self.mt5_symbol_var, width=12).grid(row=2, column=2, sticky="w")
        ttk.Label(main, text="MT5 Contract Size").grid(row=2, column=3, sticky="w")
        ttk.Entry(main, textvariable=self.mt5_contract_size_var, width=12).grid(row=2, column=4, sticky="w")

        ttk.Checkbutton(main, text="Send to Tradovate", variable=self.tradovate_send_var).grid(row=3, column=0, sticky="w")

        button_row = ttk.Frame(main)
        button_row.grid(row=4, column=0, columnspan=6, sticky="we", pady=(12, 8))
        ttk.Button(
            button_row,
            text="Buy",
            command=lambda: self._send_order("BUY"),
        ).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(
            button_row,
            text="Sell",
            command=lambda: self._send_order("SELL"),
        ).grid(row=0, column=1, padx=(0, 8))
        ttk.Button(
            button_row,
            text="Close All",
            command=self._close_all,
        ).grid(row=0, column=2)
        self.reconnect_browser_button = ttk.Button(
            button_row,
            text="Reconnect Browser",
            command=self._connect_browser,
        )
        self.reconnect_browser_button.grid(row=0, column=3, padx=(8, 0))

        ttk.Label(main, textvariable=self.atr_display_var).grid(row=5, column=0, columnspan=6, sticky="w", pady=(8, 0))
        ttk.Label(main, textvariable=self.demo_status_var).grid(row=6, column=0, columnspan=6, sticky="w", pady=(4, 0))
        
        # Separate Live status with different color
        status_frame = ttk.Frame(main)
        status_frame.grid(row=7, column=0, columnspan=6, sticky="w", pady=(4, 0))
        self.live_status_label = tk.Label(status_frame, textvariable=self.status_var, fg="green", font=('TkDefaultFont', 9, 'bold'))
        self.live_status_label.pack(anchor="w")

        # Open Positions Table
        ttk.Label(main, text="Open Positions", font=('TkDefaultFont', 10, 'bold')).grid(row=8, column=0, columnspan=6, sticky="w", pady=(16, 8))
        
        table_frame = ttk.Frame(main)
        table_frame.grid(row=9, column=0, columnspan=6, sticky="nsew")
        
        columns = ("date", "time", "ticker", "side", "open_price", "tp", "sl", "qty", "demo", "result")
        self.positions_tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=6, selectmode="extended")
        
        self.positions_tree.heading("date", text="Date")
        self.positions_tree.heading("time", text="Time")
        self.positions_tree.heading("ticker", text="Ticker")
        self.positions_tree.heading("side", text="Side")
        self.positions_tree.heading("open_price", text="Open Price")
        self.positions_tree.heading("tp", text="TP")
        self.positions_tree.heading("sl", text="SL")
        self.positions_tree.heading("qty", text="Qty")
        self.positions_tree.heading("demo", text="Demo/Live")
        self.positions_tree.heading("result", text="Result")
        
        self.positions_tree.column("date", width=80)
        self.positions_tree.column("time", width=70)
        self.positions_tree.column("ticker", width=60)
        self.positions_tree.column("side", width=50)
        self.positions_tree.column("open_price", width=80)
        self.positions_tree.column("tp", width=70)
        self.positions_tree.column("sl", width=70)
        self.positions_tree.column("qty", width=50)
        self.positions_tree.column("demo", width=70)
        self.positions_tree.column("result", width=120)
        
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.positions_tree.yview)
        self.positions_tree.configure(yscrollcommand=scrollbar.set)
        
        self.positions_tree.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        
        # Add right-click context menu for copying cell values
        self.context_menu = tk.Menu(self.root, tearoff=0)
        self.context_menu.add_command(label="Copy", command=self._copy_cell_value)
        self.positions_tree.bind("<Button-3>", self._show_context_menu)
        
        # Add dropdown for result selection
        self.result_var = tk.StringVar(value="")
        result_dropdown = ttk.Combobox(main, textvariable=self.result_var, values=["", "TP", "SL"], state="readonly", width=10)
        result_dropdown.grid(row=10, column=0, sticky="w", pady=(8, 0))
        ttk.Button(main, text="Update Result", command=self._update_selected_result).grid(row=10, column=1, sticky="w", padx=(8, 0), pady=(8, 0))

        # Chart button
        ttk.Button(main, text="Show Equity Chart", command=self._show_chart_window).grid(row=11, column=0, columnspan=6, sticky="w", pady=(12, 0))

    def _init_trade_record(self) -> None:
        self.trade_record_dir = "trade_record"
        os.makedirs(self.trade_record_dir, exist_ok=True)
        self.trade_record_file = os.path.join(
            self.trade_record_dir,
            f"trades_{datetime.now().strftime('%Y')}.csv"
        )
        self._ensure_trade_record_headers()

    def _init_chart(self) -> None:
        """Initialize the matplotlib figure for equity chart."""
        self.chart_figure = Figure(figsize=(10, 6), dpi=100)
        self.chart_ax = self.chart_figure.add_subplot(111)
        self.chart_ax.set_title("Equity Curve")
        self.chart_ax.set_xlabel("Date")
        self.chart_ax.set_ylabel("Value")
        self.chart_ax.grid(True)
        self.chart_window = None
        self.chart_canvas = None
        self.chart_sec_ax = None

    def _show_chart_window(self) -> None:
        """Show or update the equity chart window."""
        if self.chart_window is None or not tk.Toplevel.winfo_exists(self.chart_window):
            self.chart_window = tk.Toplevel(self.root)
            self.chart_window.title("Equity Curve Chart")
            self.chart_window.geometry("800x600")
            
            self.chart_canvas = FigureCanvasTkAgg(self.chart_figure, master=self.chart_window)
            self.chart_canvas.draw()
            self.chart_canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        
        self._update_chart()

    def _update_chart(self) -> None:
        """Update the chart with latest data from CSV."""
        if not os.path.exists(self.trade_record_file):
            return
        
        # Load data from CSV - only include rows with valid calculated fields
        trade_numbers = []
        dates = []
        demo_values = []
        sma_38_values = []
        equity_curve_values = []
        
        with open(self.trade_record_file, 'r', newline='') as f:
            reader = csv.DictReader(f)
            trade_count = 0
            for row in reader:
                date_str = row.get('date', '')
                demo_value_str = row.get('demo_value', '0')
                sma_38_str = row.get('38_sma', '0')
                equity_curve_str = row.get('equity_curve_trading_value', '0')
                
                # Skip rows where calculated fields are empty (newly opened trades)
                if not date_str or not str(date_str).strip():
                    continue
                if not sma_38_str or not str(sma_38_str).strip():
                    continue
                if not equity_curve_str or not str(equity_curve_str).strip():
                    continue
                
                trade_count += 1
                demo_value = float(demo_value_str) if demo_value_str and str(demo_value_str).strip() else 0.0
                sma_38 = float(sma_38_str) if sma_38_str and str(sma_38_str).strip() else 0.0
                equity_curve = float(equity_curve_str) if equity_curve_str and str(equity_curve_str).strip() else 0.0
                
                trade_numbers.append(trade_count)
                dates.append(date_str)
                demo_values.append(demo_value)
                sma_38_values.append(sma_38)
                equity_curve_values.append(equity_curve)
        
        # Clear and replot
        self.chart_ax.clear()
        self.chart_ax.set_title("Equity Curve")
        self.chart_ax.set_xlabel("Trade Number")
        self.chart_ax.set_ylabel("Value")
        self.chart_ax.grid(True)
        
        if demo_values:
            self.chart_ax.plot(trade_numbers, demo_values, label='Demo Value (Cumulative P/L)', color='blue', linewidth=2)
        
        if sma_38_values:
            self.chart_ax.plot(trade_numbers, sma_38_values, label='38 SMA', color='orange', linewidth=2, linestyle='-')
        
        if equity_curve_values:
            self.chart_ax.plot(trade_numbers, equity_curve_values, label='Equity Curve Trading Value', color='green', linewidth=2)
        
        self.chart_ax.legend()
        
        # Add secondary x-axis with dates
        if dates and trade_numbers:
            # Remove existing secondary axis if it exists
            if self.chart_sec_ax is not None:
                self.chart_sec_ax.remove()
            
            sec_ax = self.chart_ax.twiny()
            sec_ax.set_xlabel("Date")
            sec_ax.set_xlim(self.chart_ax.get_xlim())
            sec_ax.set_xticks(trade_numbers)
            sec_ax.set_xticklabels(dates, rotation=45, ha='left', fontsize=8)
            # Limit the number of date labels to avoid overcrowding
            from matplotlib.ticker import MaxNLocator
            sec_ax.xaxis.set_major_locator(MaxNLocator(nbins=10, integer=True))
            self.chart_sec_ax = sec_ax
        
        if self.chart_canvas:
            self.chart_canvas.draw()

    def _update_reverse_order_checkbox(self) -> None:
        """Update Reverse Order checkbox based on demo value vs 38 SMA."""
        if not os.path.exists(self.trade_record_file):
            return
        
        # Get the latest demo value and 38 SMA
        latest_demo_value = 0.0
        latest_sma_38 = 0.0
        
        with open(self.trade_record_file, 'r', newline='') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            if rows:
                last_row = rows[-1]
                demo_value_str = last_row.get('demo_value', '0')
                sma_38_str = last_row.get('38_sma', '0')
                
                latest_demo_value = float(demo_value_str) if demo_value_str and str(demo_value_str).strip() else 0.0
                latest_sma_38 = float(sma_38_str) if sma_38_str and str(sma_38_str).strip() else 0.0
        
        # Set checkbox: checked if demo value < 38 SMA, unchecked if >=
        if latest_demo_value < latest_sma_38:
            self.reverse_order_var.set(True)
        else:
            self.reverse_order_var.set(False)

    def _ensure_trade_record_headers(self) -> None:
        headers = [
            "date",
            "create_time",
            "trade_number",
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
        if not os.path.exists(self.trade_record_file):
            with open(self.trade_record_file, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(headers)

    def _get_commission(self, ticker: str) -> float:
        """Get round-trip commission for the given ticker."""
        commission_map = {
            "YM": 3.1,
            "ES": 3.1,
            "NQ": 3.1,
            "RTY": 3.1,
            "MYM": 1.04,
            "MES": 1.04,
            "MNQ": 1.04,
            "M2K": 1.04,
        }
        return commission_map.get(ticker, 0.0)

    def _get_multiplier(self, ticker: str) -> float:
        """Get multiplier for the given ticker."""
        multiplier_map = {
            "NQ": 20,
            "MNQ": 2,
            "ES": 50,
            "MES": 5,
            "YM": 5,
            "MYM": 0.5,
            "RTY": 50,
            "M2K": 5,
        }
        return multiplier_map.get(ticker, 20)

    def _record_trade(
        self,
        ticker: str,
        open_price: float,
        take_profit: float,
        stoploss: float,
        quantity: int,
        side: str,
        demo_value: str,
        remark: str = ""
    ) -> None:
        # Calculate bet as max(tp_distance, sl_distance) * quantity * multiplier
        tp_distance = abs(take_profit - open_price)
        sl_distance = abs(stoploss - open_price)
        multiplier = self._get_multiplier(ticker)
        bet = max(tp_distance, sl_distance) * quantity * multiplier
        
        # Get commission
        commission = self._get_commission(ticker)
        
        # Calculate cumulative demo_value (running total of profit_loss)
        cumulative_demo_value = self._get_cumulative_demo_value()
        
        # Calculate trade number
        trade_number = self._get_next_trade_number()
        
        row = [
            datetime.now().strftime('%Y-%m-%d'),
            datetime.now().strftime('%H:%M:%S'),
            trade_number,
            ticker,
            round(open_price, 2),
            round(take_profit, 2),
            round(stoploss, 2),
            quantity,
            "",  # result
            side,
            multiplier,
            round(bet, 2),  # bet
            round(commission, 2),  # commission
            "",  # profit_loss
            round(cumulative_demo_value, 2),  # demo_value (cumulative)
            "",  # 38_sma
            "",  # signal
            "",  # is_trade
            "",  # equity_curve_trading_value
            "",  # drawdown
            remark
        ]
        with open(self.trade_record_file, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(row)
        self._load_open_positions()

    def _get_next_trade_number(self) -> int:
        """Calculate the next trade number based on existing records."""
        if not os.path.exists(self.trade_record_file):
            return 1
        
        count = 0
        with open(self.trade_record_file, 'r', newline='') as f:
            reader = csv.DictReader(f)
            for row in reader:
                count += 1
        return count + 1

    def _get_cumulative_demo_value(self) -> float:
        """Calculate cumulative profit_loss from all completed trades."""
        if not os.path.exists(self.trade_record_file):
            return 0.0
        
        cumulative = 0.0
        with open(self.trade_record_file, 'r', newline='') as f:
            reader = csv.DictReader(f)
            for row in reader:
                profit_loss = row.get('profit_loss', '').strip()
                if profit_loss:
                    try:
                        cumulative += float(profit_loss)
                    except ValueError:
                        pass
        return cumulative

    def _calculate_38_sma(self, demo_values: list[float]) -> float:
        """Calculate 38-period simple moving average of demo_values."""
        if len(demo_values) < 38:
            return 0.0
        return sum(demo_values[-38:]) / 38

    def _load_open_positions(self) -> None:
        """Load open positions from CSV file (trades with empty result)."""
        self.open_positions = []
        self.positions_tree.delete(*self.positions_tree.get_children())
        
        if not os.path.exists(self.trade_record_file):
            return
        
        with open(self.trade_record_file, 'r', newline='') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Only show trades with empty result (open positions)
                if not row.get('result', '').strip():
                    self.open_positions.append(row)
                    self.positions_tree.insert("", "end", values=(
                        row.get('date', ''),
                        row.get('create_time', ''),
                        row.get('ticker', ''),
                        row.get('side', ''),
                        row.get('open_price', ''),
                        row.get('take_profit', ''),
                        row.get('stoploss', ''),
                        row.get('quantity', ''),
                        row.get('demo_value', ''),
                        row.get('result', '')
                    ))

    def _check_tp_sl_hits(self, current_price: float) -> list[dict]:
        """Check if current price hits TP/SL for any open positions."""
        hit_positions = []
        
        for position in self.open_positions:
            try:
                tp = float(position.get('take_profit', 0))
                sl = float(position.get('stoploss', 0))
                side = position.get('side', '')
                
                if side == 'BUY':
                    # For BUY: TP is above, SL is below
                    if current_price >= tp:
                        hit_positions.append((position, 'TP'))
                    elif current_price <= sl:
                        hit_positions.append((position, 'SL'))
                elif side == 'SELL':
                    # For SELL: TP is below, SL is above
                    if current_price <= tp:
                        hit_positions.append((position, 'TP'))
                    elif current_price >= sl:
                        hit_positions.append((position, 'SL'))
            except (ValueError, TypeError):
                continue
        
        return hit_positions

    def _auto_update_position_result(self, position: dict, result: str) -> None:
        """Auto-update the result for a position when TP/SL is hit."""
        # Only allow auto-update after startup to avoid unrealistic updates from historical data
        if not self._allow_auto_update:
            return
        
        # Read all rows from CSV
        rows = []
        updated = False
        
        with open(self.trade_record_file, 'r', newline='') as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            for row in reader:
                # Check if this row matches the position
                if (row.get('date') == position.get('date') and 
                    row.get('create_time') == position.get('create_time') and 
                    row.get('ticker') == position.get('ticker') and 
                    not row.get('result', '').strip()):
                    
                    # Update the result
                    row['result'] = result
                    
                    # Calculate profit_loss
                    open_price = float(row.get('open_price', 0))
                    take_profit = float(row.get('take_profit', 0))
                    stoploss = float(row.get('stoploss', 0))
                    quantity = int(row.get('quantity', 0))
                    side = row.get('side', '')
                    multiplier = float(row.get('multiplier', 1))
                    commission = float(row.get('commission', 0))
                    
                    if result == "TP":
                        exit_price = take_profit
                    else:  # SL
                        exit_price = stoploss
                    
                    if side == "BUY":
                        gross_profit = (exit_price - open_price) * quantity * multiplier
                    else:  # SELL
                        gross_profit = (open_price - exit_price) * quantity * multiplier
                    
                    profit_loss = gross_profit - commission
                    row['profit_loss'] = round(profit_loss, 2)
                    updated = True
                
                rows.append(row)
        
        if not updated:
            return
        
        # Recalculate demo_value and 38_sma for all rows
        cumulative = 0.0
        demo_values = []
        for row in rows:
            profit_loss = row.get('profit_loss', 0)
            if isinstance(profit_loss, str):
                profit_loss = profit_loss.strip()
            if profit_loss:
                try:
                    cumulative += float(profit_loss)
                except (ValueError, TypeError):
                    pass
            row['demo_value'] = round(cumulative, 2)
            demo_values.append(cumulative)
        
        # Calculate 38_sma for each row
        for i, row in enumerate(rows):
            if i >= 37:  # Need at least 38 data points (0-indexed)
                row['38_sma'] = round(self._calculate_38_sma(demo_values[:i+1]), 2)
        
        # Calculate signal and is_trade for each row
        signals = []
        for i, row in enumerate(rows):
            demo_value_str = row.get('demo_value', 0)
            demo_value = float(demo_value_str) if demo_value_str and str(demo_value_str).strip() else 0.0
            sma_38_str = row.get('38_sma', 0)
            sma_38 = float(sma_38_str) if sma_38_str and str(sma_38_str).strip() else 0.0
            
            # signal: 1 if demo_value > 38_sma, else 0
            signal = 1 if demo_value > sma_38 else 0
            row['signal'] = signal
            signals.append(signal)
            
            # is_trade: 1 if previous signal is 1, else -1
            if i == 0:
                is_trade = -1  # No previous signal for first row
            else:
                is_trade = 1 if signals[i-1] == 1 else -1
            row['is_trade'] = is_trade
        
        # Calculate equity_curve_trading_value for each row
        equity_curve_value = 0.0
        for i, row in enumerate(rows):
            is_trade = int(row.get('is_trade', -1))
            profit_loss_str = row.get('profit_loss', 0)
            if isinstance(profit_loss_str, str):
                profit_loss_str = profit_loss_str.strip()
            profit_loss = float(profit_loss_str) if profit_loss_str else 0.0
            commission_str = row.get('commission', 0)
            if isinstance(commission_str, str):
                commission_str = commission_str.strip()
            commission = float(commission_str) if commission_str else 0.0
            
            if i == 0:
                equity_curve_trading_value = 0.0  # First row starts at 0
            else:
                if is_trade == 1:
                    equity_curve_trading_value = equity_curve_value + profit_loss
                else:  # is_trade == -1
                    equity_curve_trading_value = equity_curve_value - profit_loss - (2 * commission)
            equity_curve_value = equity_curve_trading_value
            row['equity_curve_trading_value'] = round(equity_curve_trading_value, 2)
        
        # Write updated rows back to CSV
        with open(self.trade_record_file, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        
        # Refresh the table
        self._load_open_positions()
        
        # Update chart if window is open
        if self.chart_window is not None and tk.Toplevel.winfo_exists(self.chart_window):
            self.root.after(100, self._update_chart)
        
        # Update reverse order checkbox based on latest demo value vs 38 SMA
        self._update_reverse_order_checkbox()
        
        print(f"Auto-updated position {position.get('ticker')} to {result}")

    def _show_context_menu(self, event) -> None:
        """Show context menu when right-clicking on a cell."""
        # Select the item under the cursor
        item = self.positions_tree.identify_row(event.y)
        if item:
            self.positions_tree.selection_set(item)
            self.context_menu.post(event.x_root, event.y_root)

    def _copy_cell_value(self) -> None:
        """Copy the value of the selected cell to clipboard."""
        selected_items = self.positions_tree.selection()
        if not selected_items:
            return
        
        item = selected_items[0]
        values = self.positions_tree.item(item)['values']
        
        # Get the column that was clicked
        column = self.positions_tree.identify_column(self.positions_tree.winfo_pointerx() - self.positions_tree.winfo_rootx())
        if column:
            col_index = int(column[1:]) - 1  # Convert '#1' to 0, '#2' to 1, etc.
            if 0 <= col_index < len(values):
                value = str(values[col_index])
                self.root.clipboard_clear()
                self.root.clipboard_append(value)
                print(f"Copied to clipboard: {value}")

    def _update_selected_result(self) -> None:
        """Update the result column for the selected trade(s) in the CSV file."""
        selected_items = self.positions_tree.selection()
        if not selected_items:
            messagebox.showwarning("No Selection", "Please select a trade from the table first.")
            return
        
        result_value = self.result_var.get()
        if not result_value:
            messagebox.showwarning("No Result", "Please select TP or SL from the dropdown.")
            return
        
        # Collect selected trade identifiers
        selected_trades = []
        for item in selected_items:
            item_values = self.positions_tree.item(item)['values']
            selected_trades.append({
                'date': item_values[0],
                'time': item_values[1],
                'ticker': item_values[2]
            })
        
        # Read all rows from CSV
        rows = []
        updated_count = 0
        with open(self.trade_record_file, 'r', newline='') as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            for row in reader:
                # Check if this row matches any selected trade
                for selected in selected_trades:
                    if (row.get('date') == selected['date'] and 
                        row.get('create_time') == selected['time'] and 
                        row.get('ticker') == selected['ticker'] and 
                        not row.get('result', '').strip()):
                        row['result'] = result_value
                        
                        # Calculate profit_loss
                        open_price = float(row.get('open_price', 0))
                        take_profit = float(row.get('take_profit', 0))
                        stoploss = float(row.get('stoploss', 0))
                        quantity = int(row.get('quantity', 0))
                        side = row.get('side', '')
                        multiplier = float(row.get('multiplier', 1))
                        commission = float(row.get('commission', 0))
                        
                        if result_value == "TP":
                            exit_price = take_profit
                        else:  # SL
                            exit_price = stoploss
                        
                        if side == "BUY":
                            gross_profit = (exit_price - open_price) * quantity * multiplier
                        else:  # SELL
                            gross_profit = (open_price - exit_price) * quantity * multiplier
                        
                        profit_loss = gross_profit - commission
                        row['profit_loss'] = round(profit_loss, 2)
                        
                        updated_count += 1
                        break  # Only update once per row
                rows.append(row)
        
        if updated_count == 0:
            messagebox.showerror("Error", "Could not find the selected trade(s) in the CSV file.")
            return
        
        # Recalculate demo_value and 38_sma for all rows
        cumulative = 0.0
        demo_values = []
        for row in rows:
            profit_loss = row.get('profit_loss', 0)
            if isinstance(profit_loss, str):
                profit_loss = profit_loss.strip()
            if profit_loss:
                try:
                    cumulative += float(profit_loss)
                except (ValueError, TypeError):
                    pass
            row['demo_value'] = round(cumulative, 2)
            demo_values.append(cumulative)
        
        # Calculate 38_sma for each row
        for i, row in enumerate(rows):
            if i >= 37:  # Need at least 38 data points (0-indexed)
                row['38_sma'] = round(self._calculate_38_sma(demo_values[:i+1]), 2)
        
        # Calculate signal and is_trade for each row
        signals = []
        for i, row in enumerate(rows):
            demo_value_str = row.get('demo_value', 0)
            demo_value = float(demo_value_str) if demo_value_str and str(demo_value_str).strip() else 0.0
            sma_38_str = row.get('38_sma', 0)
            sma_38 = float(sma_38_str) if sma_38_str and str(sma_38_str).strip() else 0.0
            
            # signal: 1 if demo_value > 38_sma, else 0
            signal = 1 if demo_value > sma_38 else 0
            row['signal'] = signal
            signals.append(signal)
            
            # is_trade: 1 if previous signal is 1, else -1
            if i == 0:
                is_trade = -1  # No previous signal for first row
            else:
                is_trade = 1 if signals[i-1] == 1 else -1
            row['is_trade'] = is_trade
        
        # Calculate equity_curve_trading_value for each row
        equity_curve_value = 0.0
        for i, row in enumerate(rows):
            is_trade = int(row.get('is_trade', -1))
            profit_loss_str = row.get('profit_loss', 0)
            if isinstance(profit_loss_str, str):
                profit_loss_str = profit_loss_str.strip()
            profit_loss = float(profit_loss_str) if profit_loss_str else 0.0
            commission_str = row.get('commission', 0)
            if isinstance(commission_str, str):
                commission_str = commission_str.strip()
            commission = float(commission_str) if commission_str else 0.0
            
            if i == 0:
                equity_curve_trading_value = 0.0  # First row starts at 0
            else:
                if is_trade == 1:
                    equity_curve_trading_value = equity_curve_value + profit_loss
                else:  # is_trade == -1
                    equity_curve_trading_value = equity_curve_value - profit_loss - (2 * commission)
            equity_curve_value = equity_curve_trading_value
            row['equity_curve_trading_value'] = round(equity_curve_trading_value, 2)
        
        # Write updated rows back to CSV
        with open(self.trade_record_file, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        
        # Refresh the table
        self._load_open_positions()
        self.result_var.set("")  # Reset dropdown
        
        # Update chart if window is open - schedule after delay to ensure CSV is flushed
        if self.chart_window is not None and tk.Toplevel.winfo_exists(self.chart_window):
            self.root.after(100, self._update_chart)
        
        # Update reverse order checkbox based on latest demo value vs 38 SMA
        self._update_reverse_order_checkbox()
        
        messagebox.showinfo("Success", f"Updated {updated_count} trade(s) to {result_value}")

    def _refresh_symbol_data(self) -> None:
        """Refresh data from IB when symbol changes."""
        try:
            symbol = self.symbol_var.get().strip()
            if not symbol:
                messagebox.showwarning("Invalid Symbol", "Please enter a valid symbol.")
                return
            
            # Update MT5 symbol mapping if needed
            if symbol.upper() in ('NQ', 'MNQ'):
                self.mt5_symbol_var.set("NAS100_SB")
            else:
                self.mt5_symbol_var.set(symbol)
            
            # Cancel previous historical data request to avoid duplicate ticker ID error
            self.app.cancelHistoricalData(2001)
            
            # Rebuild contract with new symbol
            self.contract = build_contract(self.config, symbol)
            
            # Request min tick and cache it
            min_tick = self.app.request_contract_min_tick(2002, self.contract, self.config.timeout)
            self._cached_contract = self.contract
            self._cached_min_tick = min_tick
            
            # Clear existing bars
            self.app._bars = []
            self.app._last_atr = 0.0
            self.app._last_close = 0.0
            
            # Request new contract details and historical data
            print(
                f"Updated contract: symbol={self.contract.symbol} secType={self.contract.secType} "
                f"expiry={self.contract.lastTradeDateOrContractMonth}"
            )
            self.app.reqHistoricalData(
                2001,
                self.contract,
                "",
                self.config.duration,
                self.config.bar_size,
                self.config.what_to_show,
                self.config.use_rth,
                1,
                self.config.keep_up_to_date,
                [],
            )
            self.status_var.set(f"Loading historical bars for {symbol}...")
            self.atr_display_var.set("ATR: --")
            
        except Exception as exc:
            messagebox.showerror("Symbol Update Error", str(exc))

    def _connect_and_load(self) -> None:
        print(
            f"Connecting to IB TWS/Gateway at {self.config.host}:{self.config.port} "
            f"with client id {self.config.client_id}..."
        )
        self.app.connect(self.config.host, self.config.port, self.config.client_id)
        thread = threading.Thread(target=self.app.run, daemon=True)
        thread.start()

        if not self.app.connected_event.wait(self.config.timeout):
            messagebox.showerror("IB connection", "Timed out waiting for IB handshake.")
            self.root.after(0, self.root.destroy)
            return

        if self.mt5_app.available:
            try:
                self.mt5_app.connect()
            except Exception as exc:
                messagebox.showwarning("MT5 connection", str(exc))

        # Connect to browser after IB and MT5 are connected
        self._connect_browser()

        self.contract = build_contract(self.config, self.symbol_var.get().strip() or self.config.symbol)
        self.app.request_positions(self.config.timeout)
        min_tick = self.app.request_contract_min_tick(2002, self.contract, self.config.timeout)
        self._cached_contract = self.contract
        self._cached_min_tick = min_tick
        print(
            f"Resolved contract: symbol={self.contract.symbol} secType={self.contract.secType} "
            f"expiry={self.contract.lastTradeDateOrContractMonth}"
        )
        self.app.reqHistoricalData(
            2001,
            self.contract,
            "",
            self.config.duration,
            self.config.bar_size,
            self.config.what_to_show,
            self.config.use_rth,
            1,
            self.config.keep_up_to_date,
            [],
        )
        self.status_var.set("Loading historical bars...")

    def _poll_status(self) -> None:
        atr = self.app.last_atr
        close = self.app.last_close
        try:
            atr_mult = float(self.atr_var.get())
        except ValueError:
            atr_mult = 0.0

        # Enable auto-update after 30 seconds from startup to avoid unrealistic updates from historical data
        if not self._allow_auto_update and (datetime.now() - self._startup_time).total_seconds() > 30:
            self._allow_auto_update = True

        if atr > 0 and close > 0:
            self.atr_display_var.set(f"Last close: {close:.2f}   ATR(14): {atr:.2f}   ATR x mult: {atr * atr_mult:.2f}")
            self.status_var.set("Live")
            
            # Check if current price hits TP/SL for any open positions
            hit_positions = self._check_tp_sl_hits(close)
            for position, result in hit_positions:
                self._auto_update_position_result(position, result)
        else:
            self.atr_display_var.set("ATR: --")

        # Check browser status every 1 minute (120 iterations of 500ms)
        self._browser_check_counter += 1
        if self._browser_check_counter >= 120:
            self._browser_check_counter = 0
            if self.browser_connected and not self._check_browser_status():
                messagebox.showwarning("Browser Disconnected", "Browser has been closed. Please click 'Reconnect Browser' button to reconnect.")

        self.root.after(500, self._poll_status)

    def _bracket_distance_points(self, atr_mult: float) -> float:
        atr = self.app.last_atr
        if self.app.last_close <= 0:
            raise RuntimeError("No latest price available yet")
        if atr <= 0:
            raise RuntimeError("No ATR available yet")
        if atr_mult <= 0:
            raise ValueError("ATR Mult must be positive")
        min_tick = self.app.min_tick
        if min_tick is None or min_tick <= 0:
            raise RuntimeError("No tick size available yet")
        return round(atr * atr_mult) * min_tick

    def _ib_bracket_prices(self, action: str, distance_points: float) -> tuple[float, float]:
        last_close = self.app.last_close
        if action == "BUY":
            return last_close + distance_points, last_close - distance_points
        return last_close - distance_points, last_close + distance_points

    def _connect_browser(self) -> None:
        """Connect to browser (Firefox or Chrome) for tradovate.com automation."""
        if not PYWINAUTO_AVAILABLE:
            messagebox.showwarning("Browser Automation", "pywinauto library is not installed. Cannot connect to browser.")
            return
        
        try:
            # Try Firefox first
            try:
                app = pywinauto.Application(backend="uia").connect(title_re=".*Firefox.*", timeout=2)
                browser = app.window(title_re=".*Firefox.*")
                self.browser_app = app
                self.browser_window = browser
                self.browser_connected = True
                self.browser_name = "Firefox"
                self._update_browser_button_state()
                print("Connected to Firefox browser")
                messagebox.showinfo("Browser Connected", "Successfully connected to Firefox browser")
                self.root.focus_force()
                self.root.lift()
                return
            except:
                pass

            # Try Chrome if Firefox not found
            try:
                app = pywinauto.Application(backend="uia").connect(title_re=".*Chrome.*", timeout=2)
                browser = app.window(title_re=".*Chrome.*")
                self.browser_app = app
                self.browser_window = browser
                self.browser_connected = True
                self.browser_name = "Chrome"
                self._update_browser_button_state()
                print("Connected to Chrome browser")
                messagebox.showinfo("Browser Connected", "Successfully connected to Chrome browser")
                self.root.focus_force()
                self.root.lift()
                return
            except:
                pass
            
            # Neither browser found
            self._disconnect_browser()
            messagebox.showwarning("Browser Not Found", "Could not find Chrome or Firefox browser. Please ensure browser is running.")
            self.root.focus_force()
            self.root.lift()
            
        except Exception as e:
            self._disconnect_browser()
            messagebox.showerror("Browser Connection Error", f"Error connecting to browser: {str(e)}")
            self.root.focus_force()
            self.root.lift()

    def _disconnect_browser(self) -> None:
        """Clear browser connection state and cached references."""
        self.browser_connected = False
        self.browser_app = None
        self.browser_window = None
        self.browser_name = ""
        self._cached_tradovate_tab = None
        self._update_browser_button_state()

    def _update_browser_button_state(self) -> None:
        """Update reconnect browser button state based on connection status."""
        if self.reconnect_browser_button is None:
            return
        
        if self.browser_connected:
            self.reconnect_browser_button.config(text="Tradovate Connected", state="disabled")
        else:
            self.reconnect_browser_button.config(text="Reconnect Browser", state="normal")

    def _check_browser_status(self) -> bool:
        """Check if browser is still connected and running."""
        if not self.browser_connected or self.browser_window is None:
            return False
        
        try:
            # Quick check if browser window still exists
            exists = self.browser_window.exists()
            if not exists:
                self._disconnect_browser()
            return exists
        except:
            self._disconnect_browser()
            return False

    def _find_tradovate_tab(self, browser) -> object | None:
        """Find the tradovate.com tab in browser descendants."""
        start = time.time()
        for child in browser.descendants():
            if hasattr(child, 'window_text') and 'tradovate.com' in child.window_text().lower():
                print(f"find tradovate tab time: {round(time.time() - start, 2)}")
                return child
        return None

    def _send_tradovate_shortcut(self, action: str) -> None:
        """Send keyboard shortcut to tradovate.com browser tab."""
        if not PYWINAUTO_AVAILABLE:
            messagebox.showwarning("Browser Automation", "pywinauto library is not installed. Cannot send keyboard shortcuts to tradovate.com")
            return
        
        # Check if browser is still connected
        if not self._check_browser_status():
            messagebox.showwarning("Browser Disconnected", "Browser has been closed or is not connected. Please click 'Reconnect Browser' button.")
            return
        
        try:
            browser = self.browser_window
            if browser is None:
                messagebox.showwarning("Browser Not Connected", "Browser connection is not available. Please click 'Reconnect Browser' button.")
                return
            
            # Try to find the tab with tradovate.com - use cached reference if available
            tradovate_tab = self._cached_tradovate_tab
            
            # If no cached tab or cached tab is invalid, search for it
            if tradovate_tab is None:
                tradovate_tab = self._find_tradovate_tab(browser)
                if tradovate_tab is None:
                    messagebox.showwarning("Tab Not Found", f"Could not find a tab with tradovate.com in {self.browser_name}")
                    return
                self._cached_tradovate_tab = tradovate_tab
            
            # Set focus on the tradovate tab
            try:
                tradovate_tab.set_focus()
                time.sleep(random.random()*0.2)
                send_keys("{ESC}")
            except:
                # If cached tab is invalid, clear it and try to find again
                self._cached_tradovate_tab = None
                tradovate_tab = self._find_tradovate_tab(browser)
                if tradovate_tab is None:
                    messagebox.showwarning("Tab Not Found", f"Could not find a tab with tradovate.com in {self.browser_name}")
                    return
                self._cached_tradovate_tab = tradovate_tab
                
                tradovate_tab.set_focus()
                time.sleep(random.random()*0.2)
                send_keys("{ESC}")
            
            # Determine which shortcut to send based on action and reverse order checkbox
            send_keys("^%b") if action == "BUY" else send_keys("^%s")

        except Exception as e:
            messagebox.showwarning("Browser Automation Error", f"Could not send keyboard shortcut to tradovate.com: {str(e)}")

    def _send_order(self, action: str) -> None:
        try:
            symbol = self.symbol_var.get().strip()
            if not symbol:
                raise ValueError("Symbol is required")
            quantity = int(self.qty_var.get())
            atr_mult = float(self.atr_var.get())
            mt5_symbol = self.mt5_symbol_var.get().strip()
            mt5_contract_size = float(self.mt5_contract_size_var.get())
            distance_points = self._bracket_distance_points(atr_mult)
            
            # Use cached contract and min_tick if available, otherwise build and request
            if self._cached_contract is None or self._cached_min_tick is None:
                self.contract = build_contract(self.config, symbol)
                min_tick = self.app.request_contract_min_tick(2002, self.contract, self.config.timeout)
                self._cached_contract = self.contract
                self._cached_min_tick = min_tick
            else:
                self.contract = self._cached_contract
                min_tick = self._cached_min_tick
            
            take_profit, stop_loss = self._ib_bracket_prices(action, distance_points)
            take_profit = round(take_profit / min_tick) * min_tick
            stop_loss = round(stop_loss / min_tick) * min_tick
            
            status = []
            
            # Always record as demo trade
            demo_price = self.app.last_close
            self.demo_status_var.set(
                f"DEMO MODE - {action} {quantity} {symbol} | "
                f"Executed: {demo_price:.2f} | TP: {take_profit:.2f} | SL: {stop_loss:.2f}"
            )
            status.append("DEMO MODE")
            
            # Send IB order only if checkbox is checked
            if self.ib_send_var.get():
                self.demo_status_var.set("")
                order_id = self.app.place_bracket_market_order(
                    self.contract,
                    action,
                    quantity,
                    take_profit,
                    stop_loss,
                )
                status.append(f"IB #{order_id}")
            
            # Send MT5 order only if checkbox is checked
            if self.mt5_send_var.get() and self.mt5_app.available and self.mt5_app.connected:
                if self.reverse_order_var.get():
                    mt5_action = "SELL" if action == "BUY" else "BUY"
                else:
                    mt5_action = action
                mt5_order_id = self.mt5_app.place_bracket_market_order(
                    mt5_symbol or symbol,
                    mt5_action,
                    float(quantity),
                    mt5_contract_size,
                    distance_points,
                    distance_points,
                )
                status.append(f"MT5 #{mt5_order_id} ({mt5_action})")
            
            # Send keyboard shortcut to tradovate.com if checkbox is checked
            if self.tradovate_send_var.get():
                if self.reverse_order_var.get():
                    tradovate_action = "SELL" if action == "BUY" else "BUY"
                else:
                    tradovate_action = action
                self._send_tradovate_shortcut(tradovate_action)
            
            # Record trade once after all orders are sent
            remark = ", ".join(status)
            self._record_trade(
                ticker=symbol,
                open_price=self.app.last_close,
                take_profit=take_profit,
                stoploss=stop_loss,
                quantity=quantity,
                side=action,
                demo_value="LIVE",
                remark=remark
            )
                
            self.status_var.set(f"Sent {action} bracket order: " + ", ".join(status))
        except Exception as exc:
            messagebox.showerror("Order error", str(exc))

    def _close_all(self) -> None:
        try:
            symbol = self.symbol_var.get().strip()
            if not symbol:
                raise ValueError("Symbol is required")
            mt5_symbol = self.mt5_symbol_var.get().strip()
            self.contract = build_contract(self.config, symbol)
            
            status = []
            
            # Always record as demo trade
            self.demo_status_var.set(
                f"DEMO MODE - CLOSE {symbol}"
            )
            status.append("DEMO MODE")
            
            # Send IB close order only if checkbox is checked
            if self.ib_send_var.get():
                order_id = self.app.close_position(self.contract)
                status.append(f"IB #{order_id}")
            
            # Send MT5 close order only if checkbox is checked
            if self.mt5_send_var.get() and self.mt5_app.available and self.mt5_app.connected:
                mt5_order_id = self.mt5_app.close_position(mt5_symbol or symbol)
                status.append(f"MT5 #{mt5_order_id}")
            
            # Send keyboard shortcut to tradovate.com if checkbox is checked
            if self.tradovate_send_var.get():
                self._send_tradovate_shortcut("CLOSE")
            
            # Update all open trades with result="CLOSE" and profit_loss=0
            self._update_all_open_positions_to_closed()
            
            self.status_var.set("Sent close-all order: " + ", ".join(status))
        except Exception as exc:
            messagebox.showerror("Close error", str(exc))

    def _update_all_open_positions_to_closed(self) -> None:
        """Update all open positions to have result='CLOSE' and profit_loss=0."""
        if not os.path.exists(self.trade_record_file):
            return
        
        # Read all rows from CSV
        rows = []
        updated_count = 0
        
        with open(self.trade_record_file, 'r', newline='') as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            for row in reader:
                # Update all rows with empty result (open positions)
                if not row.get('result', '').strip():
                    row['result'] = "CLOSE"
                    row['profit_loss'] = 0
                    updated_count += 1
                rows.append(row)
        
        if updated_count == 0:
            return
        
        # Recalculate demo_value and 38_sma for all rows
        cumulative = 0.0
        demo_values = []
        for row in rows:
            profit_loss = row.get('profit_loss', 0)
            if isinstance(profit_loss, str):
                profit_loss = profit_loss.strip()
            if profit_loss:
                try:
                    cumulative += float(profit_loss)
                except (ValueError, TypeError):
                    pass
            row['demo_value'] = round(cumulative, 2)
            demo_values.append(cumulative)
        
        # Calculate 38_sma for each row
        for i, row in enumerate(rows):
            if i >= 37:  # Need at least 38 data points (0-indexed)
                row['38_sma'] = round(self._calculate_38_sma(demo_values[:i+1]), 2)
        
        # Calculate signal and is_trade for each row
        signals = []
        for i, row in enumerate(rows):
            demo_value_str = row.get('demo_value', 0)
            demo_value = float(demo_value_str) if demo_value_str and str(demo_value_str).strip() else 0.0
            sma_38_str = row.get('38_sma', 0)
            sma_38 = float(sma_38_str) if sma_38_str and str(sma_38_str).strip() else 0.0
            
            # signal: 1 if demo_value > 38_sma, else 0
            signal = 1 if demo_value > sma_38 else 0
            row['signal'] = signal
            signals.append(signal)
            
            # is_trade: 1 if previous signal is 1, else -1
            if i == 0:
                is_trade = -1  # No previous signal for first row
            else:
                is_trade = 1 if signals[i-1] == 1 else -1
            row['is_trade'] = is_trade
        
        # Calculate equity_curve_trading_value for each row
        equity_curve_value = 0.0
        for i, row in enumerate(rows):
            is_trade = int(row.get('is_trade', -1))
            profit_loss_str = row.get('profit_loss', 0)
            if isinstance(profit_loss_str, str):
                profit_loss_str = profit_loss_str.strip()
            profit_loss = float(profit_loss_str) if profit_loss_str else 0.0
            commission_str = row.get('commission', 0)
            if isinstance(commission_str, str):
                commission_str = commission_str.strip()
            commission = float(commission_str) if commission_str else 0.0
            
            if i == 0:
                equity_curve_trading_value = 0.0  # First row starts at 0
            else:
                if is_trade == 1:
                    equity_curve_trading_value = equity_curve_value + profit_loss
                else:  # is_trade == -1
                    equity_curve_trading_value = equity_curve_value - profit_loss - (2 * commission)
            equity_curve_value = equity_curve_trading_value
            row['equity_curve_trading_value'] = round(equity_curve_trading_value, 2)
        
        # Write updated rows back to CSV
        with open(self.trade_record_file, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        
        # Refresh the table
        self._load_open_positions()
        
        # Update chart if window is open
        if self.chart_window is not None and tk.Toplevel.winfo_exists(self.chart_window):
            self.root.after(100, self._update_chart)
        
        # Update reverse order checkbox based on latest demo value vs 38 SMA
        self._update_reverse_order_checkbox()
        
        print(f"Updated {updated_count} open position(s) to CLOSED")

    def _on_close(self) -> None:
        try:
            if self.app.isConnected():
                self.app.disconnect()
            self.mt5_app.shutdown()
        finally:
            self.root.quit()
            self.root.destroy()


def main() -> int:
    config = load_config()
    root = tk.Tk()
    TradingGUI(root, config)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# todo: demo trade logic
# todo: change the layout, move 'reverse order' and 'atr multi' to the 1st row, delete 'demo trade', add checkbox before IB and MT5 to decide sending roders
# todo: add drawdown to the chart
# todo: don't show Demo/Live and Result, show the current bet and diff to 38 SMA