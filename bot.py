import logging
import asyncio
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, MessageHandler, filters, ContextTypes
import httpx
from dotenv import load_dotenv
import os
import base58
from datetime import datetime

# Load environment variables from .env file
load_dotenv()

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

logger = logging.getLogger(__name__)

# Define API URLs
DEXSCREENER_API_URL = "https://api.dexscreener.com/latest/dex/search/?q="

def is_valid_base58(address: str) -> bool:
    try:
        base58.b58decode(address)
        return True
    except ValueError:
        return False

def is_contract_address(address: str) -> bool:
    return is_valid_base58(address) or (len(address) == 42 and address.startswith("0x"))

async def fetch_data(url: str, headers: dict = None) -> dict:
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            return response.json()
        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            logger.error(f"Error fetching data from {url}: {e}")
        return None

async def get_dexscreener_token_info(contract_address: str) -> dict:
    url = f"{DEXSCREENER_API_URL}{contract_address}"
    return await fetch_data(url)

def format_price_change(change: float) -> str:
    return f"🟢{change:.2f}%" if change > 0 else f"🔴{change:.2f}%" if change < 0 else f"{change:.2f}%"

def format_number(number) -> str:
    return f"{number:,.2f}" if isinstance(number, (int, float)) else 'N/A'

def format_timestamp(timestamp: int) -> str:
    dt = datetime.utcfromtimestamp(timestamp / 1000)  # Convert from milliseconds to seconds
    return dt.strftime("%Y-%m-%d %H:%M:%S")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    contract_address = update.message.text.strip()
    
    if not is_contract_address(contract_address):
        await update.message.reply_text("Not a contract address")
        return
    
    info_data = await get_dexscreener_token_info(contract_address)
    
    if info_data and 'pairs' in info_data and info_data['pairs']:
        info = info_data['pairs'][0]
        chain_name = info.get('chainId', 'N/A').capitalize()
        base_token = info.get('baseToken', {})
        quote_token = info.get('quoteToken', {})
        market_data = info.get('priceChange', {})
        liquidity = info.get('liquidity', {})
        volume_24h = info.get('volume', {}).get('h24', 'N/A')
        txns = info.get('txns', {})
        pair_created_at = info.get('pairCreatedAt', 0)
        chart_url = info.get('url', '')

        buys_5m = txns.get('m5', {}).get('buys', 'N/A')
        sells_5m = txns.get('m5', {}).get('sells', 'N/A')
        buys_1h = txns.get('h1', {}).get('buys', 'N/A')
        sells_1h = txns.get('h1', {}).get('sells', 'N/A')
        buys_24h = txns.get('h24', {}).get('buys', 'N/A')
        sells_24h = txns.get('h24', {}).get('sells', 'N/A')
        
        token_symbol = base_token.get('symbol', 'N/A')
        
        price_change_1h = market_data.get('h1', 0.0)
        price_change_6h = market_data.get('h6', 0.0)
        price_change_24h = market_data.get('h24', 0.0)
        
        pair_created_at_formatted = format_timestamp(pair_created_at) if pair_created_at else 'N/A'
        
        response_message = (
            f"<b>Chain:</b> {chain_name}\n"
            f"\n"
            f"<b>Token Name:</b> {base_token.get('name', 'N/A')}\n"
            f"<b>Symbol:</b> {token_symbol}\n"
            f"<b>Current Price (USD):</b> ${info.get('priceUsd', 'N/A')}\n"
            f"<b>Market Cap (USD):</b> ${format_number(liquidity.get('usd'))}\n"
            f"<b>Liquidity (USD):</b> ${format_number(liquidity.get('usd'))}\n"
            f"<b>24h Volume (USD):</b> ${format_number(volume_24h)}\n"
            f"\n"
            f"<b>Buys/Sells (5m):</b> {buys_5m}/{sells_5m}\n"
            f"<b>Buys/Sells (1h):</b> {buys_1h}/{sells_1h}\n"
            f"<b>Buys/Sells (24h):</b> {buys_24h}/{sells_24h}\n"
            f"<b>Pair Created At:</b> {pair_created_at_formatted}\n"
            f"\n"
            f"<b>Price Change (1h):</b> {format_price_change(price_change_1h)}\n"
            f"<b>Price Change (6h):</b> {format_price_change(price_change_6h)}\n"
            f"<b>Price Change (24h):</b> {format_price_change(price_change_24h)}\n"
            f"<a href='{chart_url}'>Chart</a>"
        )
    else:
        response_message = "Sorry, I couldn't retrieve the information. Please check the contract address and try again."

    await update.message.reply_text(response_message, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

def main() -> None:
    """Start the bot."""
    # Load the token from the environment variable
    token = os.getenv('TELEGRAM_BOT_API_TOKEN')

    # Create the Application and pass it your bot's token.
    application = Application.builder().token(token).build()

    # Handle messages that are contract addresses
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Start the Bot
    application.run_polling()

if __name__ == '__main__':
    main()