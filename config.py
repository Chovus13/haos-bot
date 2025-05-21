import os
from dotenv import load_dotenv

load_dotenv()

# Trading par
PAR = os.getenv('ETHBTC', 'ETH/BTC')

# Postavke za zidove
WALL_RANGE_SPREAD = float(os.getenv('WALL_RANGE_SPREAD', 0.00002))  # Vraćamo na 0.00002
MIN_WALL_VOLUME = float(os.getenv('MIN_WALL_VOLUME', 70))

# Preciznost
PRICE_PRECISION = int(os.getenv('PRICE_PRECISION', 5))

# Strategija
TARGET_DIGITS = [int(d) for d in os.getenv('TARGET_DIGITS', '2,3,7,8').split(',')]
SPECIAL_DIGITS = [int(d) for d in os.getenv('SPECIAL_DIGITS', '1,9').split(',')]
PROFIT_TARGET = float(os.getenv('PROFIT_TARGET', 0.00010))

# Parametri za trejd
AMOUNT = float(os.getenv('AMOUNT', 0.06))  # Fiksni Amount za trejd (npr. 0.01 ETH)
LEVERAGE = int(os.getenv('LEVERAGE', 3))  # Fiksni Leverage (npr. 3x)