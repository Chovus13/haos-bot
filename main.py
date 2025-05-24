from fastapi import FastAPI, WebSocket, Request
from fastapi.middleware.cors import CORSMiddleware
from config import AMOUNT, LEVERAGE, set_rokada_status, get_rokada_status
from orderbook import filter_walls, detect_trend
from levels import generate_signals
import logging
import logging.handlers
import asyncio
import aiohttp
import ccxt.async_support as ccxt
import os
import json
from typing import List
from dotenv import load_dotenv
import time
import telegram

app = FastAPI()
logger = logging.getLogger(__name__)



load_dotenv()


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], ### ["http://your-frontend-domain.com"],  # Be more specific in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Globalne promenljive
ws_clients: List[WebSocket] = []
last_bids = []
last_asks = []
bot_running = False
leverage = 1
trade_amount = 0.05
active_trades = []
rokada_status = "off"
LEVERAGE = 1
AMOUNT = 0.05
cached_data = None

def get_rokada_status():
    return rokada_status

def set_rokada_status(status):
    global rokada_status
    if status in ["on", "off"]:
        rokada_status = status
        return True
    return False

# Podešavanje logger-a
os.makedirs('logs', exist_ok=True)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# File handler za logs/bot.log
file_handler = logging.FileHandler('logs/bot.log')
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
logger.addHandler(file_handler)

# Stream handler za konzolu
stream_handler = logging.StreamHandler()
stream_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
logger.addHandler(stream_handler)

# Funkcija za slanje logova klijentima
async def send_logs_to_clients(message, level):
    if not ws_clients:  # Provera da li je lista prazna
        return
    log_message = {'type': 'log', 'message': f"{level}: {message}"}
    for client in ws_clients[:]:  # Kopija liste da izbegnemo greške pri iteraciji
        try:
            await client.send_text(json.dumps(log_message))
        except Exception as e:
            logger.error(f"Greška pri slanju logova klijentu: {str(e)}")
            ws_clients.remove(client)  # Uklanjamo klijenta ako je diskonektovan

# WebSocket logging handler
class WebSocketLoggingHandler(logging.Handler):
    def emit(self, record):
        log_entry = self.format(record)
        level = record.levelname
        asyncio.create_task(send_logs_to_clients(log_entry, level))

ws_handler = WebSocketLoggingHandler()
ws_handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
logger.addHandler(ws_handler)



# Inicijalizacija CCXT exchange-a
exchange = ccxt.binance({
    'apiKey': os.getenv('API_KEY'),
    'secret': os.getenv('API_SECRET'),
    'enableRateLimit': True,
})
logger.info(f"API ključevi: key={os.getenv('API_KEY')[:4]}..., secret={os.getenv('API_SECRET')[:4]}...")

# Provera balansa ---ja ubacio
async def balance_check():
    global bot_running, leverage, trade_amount
    exchange.options['defaultType'] = 'future'
    try:
        balance = await exchange.fetch_balance()
        eth_balance = balance['ETH']['free'] if 'ETH' in balance else 0
        if eth_balance < trade_amount:
            logger.error(f"Nedovoljno balansa za trejd: {eth_balance} ETH, potrebno: {trade_amount} ETH")
            return
    except Exception as e:
        logger.error(f"Greška pri proveri balansa: {str(e)}")
        return

async def fetch_current_data():
    orderbook = await exchange.fetch_order_book('ETH/BTC', limit=20)  # Smanjen limit
    current_price = (float(orderbook['bids'][0][0]) + float(orderbook['asks'][0][0])) / 2
    walls = filter_walls(orderbook, current_price)
    trend = detect_trend(orderbook, current_price)
    return current_price, walls, trend


# WebSocket konekcija sa Binance-om
async def connect_binance_ws():
    while True:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect('wss://fstream.binance.com/ws/ethbtc@depth@100ms') as ws:
                    logger.info("Povezan na Binance WebSocket")
                    while True:
                        try:
                            msg = await asyncio.wait_for(ws.receive_json(), timeout=60.0)
                            if ws.closed:
                                logger.warning("Binance WebSocket zatvoren, pokušavam ponovno povezivanje")
                                break
                            yield msg
                        except asyncio.TimeoutError:
                            logger.info("Šaljem ping poruku Binance WebSocket-u")
                            await ws.ping()
                        except Exception as e:
                            logger.error(f"Greška u WebSocket obradi: {str(e)}")
                            break
        except Exception as e:
            logger.error(f"Greška u Binance WebSocket konekciji: {str(e)}")
            await asyncio.sleep(5)

# # WebSocket endpoint
# @app.websocket("/ws")
# async def websocket_endpoint(websocket: WebSocket):
#     await websocket.accept()
#     ws_clients.append(websocket)
#     logger.info("Klijentski WebSocket povezan")
#     last_send_time = 0
#     global last_bids, last_asks
#
#     try:
#         async for msg in connect_binance_ws():
#             current_time = time.time()
#             if current_time - last_send_time < 0.2:
#                 continue
#
#             new_bids = msg.get('bids') or msg.get('b')
#             new_asks = msg.get('asks') or msg.get('a')
#
#             if new_bids:
#                 last_bids = new_bids
#             if new_asks:
#                 last_asks = new_asks
#
#             if not last_bids or not last_asks:
#                 logger.debug("Čekam na prvi validan orderbook...")
#                 continue
#
#             orderbook = {
#                 'bids': [[float(bid[0]), float(bid[1])] for bid in last_bids],
#                 'asks': [[float(ask[0]), float(ask[1])] for ask in last_asks]
#             }
#
#             if not orderbook['bids'] or not orderbook['asks']:
#                 continue
#
#             try:
#                 current_price = (float(orderbook['bids'][0][0]) + float(orderbook['asks'][0][0])) / 2
#             except (IndexError, ValueError) as e:
#                 logger.error("Greška pri izračunavanju cene: %s", str(e))
#                 continue
#
#             walls = filter_walls(orderbook, current_price)
#             trend = detect_trend(orderbook, current_price)
#
#             # Automatski uključivanje Rokade ako postoje zidovi
#             if walls['support'] or walls['resistance']:
#                 set_rokada_status("on")
#
#             signals = generate_signals(current_price, walls, trend, rokada_status=get_rokada_status())
#
#             updated_trades = []
#             for trade in active_trades:
#                 trade['current_price'] = current_price
#                 trade['status'] = 'winning' if (
#                             trade['type'] == 'LONG' and current_price > trade['entry_price']) else 'losing'
#                 updated_trades.append(trade)
#
#             response = {
#                 'type': 'data',
#                 'price': round(current_price, 5),
#                 'support': len(walls['support']),
#                 'resistance': len(walls['resistance']),
#                 'support_walls': walls['support'],
#                 'resistance_walls': walls['resistance'],
#                 'trend': trend,
#                 'signals': signals,
#                 'rokada_status': get_rokada_status(),  # Ispravljeno: poziv funkcije
#                 'active_trades': updated_trades,
#                 'ws_latency': round((time.time() - current_time) * 1000, 2),
#                 'debug': {
#                     'bids': orderbook['bids'][:3],
#                     'asks': orderbook['asks'][:3],
#                     'walls': walls,
#                     'signals': signals
#                 }
#             }
#             rest_start_time = time.time()
#             try:
#                 await exchange.fetch_order_book('ETH/BTC', limit=50)  # Povećano na 50
#                 rest_latency = round((time.time() - rest_start_time) * 1000, 2)
#             except Exception as e:
#                 logger.error(f"Greška pri merenju REST latencije: {str(e)}")
#                 rest_latency = 'N/A'
#             response['rest_latency'] = rest_latency
#
#             try:
#                 logger.info(f"Šaljem podatke preko WebSocket-a: {response}")
#                 await websocket.send_text(json.dumps(response))
#             except RuntimeError as e:
#                 logger.warning("Pokušaj slanja poruke zatvorenom WS: %s", e)
#                 break
#
#             last_send_time = current_time
#
#     except Exception as e:
#         logger.error("WebSocket greška: %s", str(e))
#     finally:
#         if websocket in ws_clients:
#             ws_clients.remove(websocket)
#         await websocket.close()
#         logger.info("Klijentski WebSocket zatvoren")


@app.websocket('/ws')
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    logger.info("Klijentski WebSocket povezan")
    try:
        while True:
            await websocket.receive_text()
            orderbook = await exchange.fetch_order_book('ETH/BTC', limit=50)
            current_price = (float(orderbook['bids'][0][0]) + float(orderbook['asks'][0][0])) / 2
            walls = filter_walls(orderbook, current_price)
            trend = detect_trend(orderbook, current_price)
            signals = generate_signals(current_price, walls, trend, rokada_status=get_rokada_status())
            data = {
                "type": "data",
                "price": current_price,
                "support": len(walls.get("support", [])),
                "resistance": len(walls.get("resistance", [])),
                "support_walls": walls.get("support", []),
                "resistance_walls": walls.get("resistance", []),
                "trend": trend,
                "signals": signals,
                "balance": 0,
                "balance_currency": "ETH",
                "extra_balances": {"BTC": 0, "USDT": 0},
                "rokada_status": get_rokada_status(),
                "active_trades": active_trades,
                "ws_latency": 0,
                "rest_latency": 0
            }
            await websocket.send_json(data)
            await asyncio.sleep(5)
    except Exception as e:
        logger.error(f"WebSocket greška: {str(e)}")
    finally:
        await websocket.close()
        logger.info("Klijentski WebSocket zatvoren")





@app.get('/get_data')
async def get_data():
    global cached_data
    if cached_data and (time.time() - cached_data['timestamp'] < 5):
        logger.info("Vraćam keširane podatke")
        return cached_data['data']

    try:
        orderbook = await exchange.fetch_order_book('ETH/BTC', limit=50)
        current_price = (float(orderbook['bids'][0][0]) + float(orderbook['asks'][0][0])) / 2
        walls = filter_walls(orderbook, current_price)
        trend = detect_trend(orderbook, current_price)
        signals = generate_signals(current_price, walls, trend, rokada_status=get_rokada_status())
        exchange.options['defaultType'] = 'future'
        try:
            balance = await exchange.fetch_balance()
            logger.info(f"Balans: {balance}")
            eth_balance = balance.get('ETH', {}).get('free', 0)
            btc_balance = balance.get('BTC', {}).get('free', 0)
            usdt_balance = balance.get('USDT', {}).get('free', 0)
        except Exception as e:
            logger.error(f"Greška pri očitavanju balansa: {e}")
            eth_balance = btc_balance = usdt_balance = 0

        data = {
            "price": current_price,
            "support": len(walls.get("support", [])),
            "resistance": len(walls.get("resistance", [])),
            "support_walls": walls.get("support", []),
            "resistance_walls": walls.get("resistance", []),
            "trend": trend,
            "signals": signals,
            "balance": eth_balance,
            "balance_currency": "ETH",
            "extra_balances": {"BTC": btc_balance, "USDT": usdt_balance},
            "rokada_status": get_rokada_status(),
            "active_trades": active_trades
        }
        cached_data = {'data': data, 'timestamp': time.time()}
        logger.info(f"Vraćam sveže podatke: {data}")
        return data
    except Exception as e:
        logger.error(f"Error fetching data: {e}")
        return {"error": "Failed to fetch data"}

@app.get('/start_trade/{signal_index}')
async def start_trade(signal_index: int):
    try:
        exchange.options['defaultType'] = 'future'
        await exchange.set_leverage(LEVERAGE, 'ETH/BTC')
        await exchange.set_margin_mode('isolated', 'ETH/BTC')

        balance = await exchange.fetch_balance()
        eth_balance = balance['ETH']['free'] if 'ETH' in balance else 0
        if eth_balance < 0.01:
            logger.error(f"Nedovoljan balans: {eth_balance} ETH")
            return {'error': f"Nedovoljan balans: {eth_balance} ETH"}

        orderbook = await exchange.fetch_order_book('ETH/BTC', limit=100)
        current_price = (float(orderbook['bids'][0][0]) + float(orderbook['asks'][0][0])) / 2
        walls = filter_walls(orderbook, current_price)
        trend = detect_trend(orderbook, current_price)
        signals = generate_signals(current_price, walls, trend)

        if signal_index < 0 or signal_index >= len(signals):
            logger.error(f"Nevažeći indeks signala: {signal_index}")
            return {'error': 'Nevažeći indeks signala'}

        signal = signals[signal_index]
        if signal['type'] == 'LONG':
            order = await exchange.create_limit_buy_order(
                'ETH/BTC',
                AMOUNT,
                signal['entry_price'],
                params={'leverage': LEVERAGE}
            )
        else:
            order = await exchange.create_limit_sell_order(
                'ETH/BTC',
                AMOUNT,
                signal['entry_price'],
                params={'leverage': LEVERAGE}
            )

        trade = {
            'type': signal['type'],
            'entry_price': signal['entry_price'],
            'stop_loss': signal['stop_loss'],
            'take_profit': signal['take_profit'],
            'order': order
        }
        active_trades.append(trade)
        logger.info(f"Započet trejd: {trade}")
        return {'message': 'Trejd započet', 'trade': trade}
    except Exception as e:
        logger.error(f"Greška pri startovanju trejda: {str(e)}")
        return {'error': str(e)}

@app.post('/start_bot')
async def startBot(data: dict):
    global bot_running, leverage, trade_amount
    logger.info(f"Primljen POST /start_bot: {data}")
    leverage = data.get('leverage', LEVERAGE)
    trade_amount = data.get('amount', AMOUNT)
    if trade_amount < 0.05:
        logger.error("Amount is too low")
        return {'status': 'error', 'message': 'Amount must be at least 0.05 ETH'}
    if leverage not in [1, 3, 5, 10]:
        logger.error(f"Invalid leverage: {leverage}")
        return {'status': 'error', 'message': 'Leverage must be 1, 3, 5, or 10'}
    if bot_running:
        logger.warning("Bot is already running")
        return {'status': 'error', 'message': 'Bot is already running'}
    bot_running = True
    logger.info(f"Bot started with leverage={leverage}, amount={trade_amount}")
    return {'status': 'success', 'leverage': leverage, 'amount': trade_amount}


@app.post('/stop_bot')
async def stopBot():
    global bot_running
    logger.info("Primljen POST /stop_bot")
    if not bot_running:
        logger.warning("Bot is not running")
        return {'status': 'error', 'message': 'Bot is not running'}
    bot_running = False
    logger.info("Bot stopped")
    return {'status': 'success'}

@app.post('/set_rokada')
async def set_rokada(data: dict):
    status = data.get('status')
    logger.info(f"Received request to set rokada status to: {status}")
    success = set_rokada_status(status)
    if success:
        orderbook = await exchange.fetch_order_book('ETH/BTC', limit=50)
        current_price = (float(orderbook['bids'][0][0]) + float(orderbook['asks'][0][0])) / 2
        walls = filter_walls(orderbook, current_price)
        trend = detect_trend(orderbook, current_price)
        signals = generate_signals(current_price, walls, trend, rokada_status=get_rokada_status())
        return {'status': get_rokada_status(), 'signals': signals}
    return {'error': 'Status mora biti "on" ili "off"'}


@app.on_event("shutdown")
async def shutdown_event():
    await exchange.close()
    logger.info("Exchange zatvoren prilikom gašenja aplikacije")


# dodao mi AI od PyCharm
@app.middleware("http")
async def add_cache_headers(request: Request, call_next):
    response = await call_next(request)
    if request.url.path == "/get_data":  # Add caching only for specific endpoints
        response.headers["Cache-Control"] = "public, max-age=5"  # Cache for 5 seconds
    return response

#@app.on_event("startup")
#async def startup_event():
#    await exchange.close()
#    logger.info("Provera balansa i ostatka aplikacije")
