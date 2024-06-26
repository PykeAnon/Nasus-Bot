import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import Application, MessageHandler, CallbackQueryHandler, filters, ContextTypes
import httpx
from dotenv import load_dotenv
import os
import base58
from datetime import datetime, timedelta
import html

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
    if len(address) in range(32, 45):  # Solana addresses typically range from 32 to 44 characters
        try:
            base58.b58decode(address)
            return True
        except ValueError:
            return False
    return False

def is_ethereum_address(address: str) -> bool:
    return len(address) == 42 and address.startswith("0x")

def is_contract_address(address: str) -> bool:
    return is_valid_base58(address) or is_ethereum_address(address)

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
    try:
        return f"{float(number):,.2f}" if number is not None else 'N/A'
    except (ValueError, TypeError):
        return 'N/A'

def calculate_age(pair_created_at: int) -> str:
    if pair_created_at:
        creation_date = datetime.utcfromtimestamp(pair_created_at / 1000)
        age = datetime.utcnow() - creation_date
        if age.days > 365:
            years = age.days // 365
            months = (age.days % 365) // 30
            return f"{years} year(s), {months} month(s)"
        elif age.days > 30:
            months = age.days // 30
            days = age.days % 30
            return f"{months} month(s), {days} day(s)"
        elif age.days > 0:
            return f"{age.days} day(s)"
        else:
            hours, remainder = divmod(age.seconds, 3600)
            minutes, _ = divmod(remainder, 60)
            return f"{hours} hour(s), {minutes} minute(s)"
    return 'N/A'

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message_text = update.message.text.strip()

    # Check if the message contains a valid contract address
    if not is_contract_address(message_text):
        return  # Ignore the message if it doesn't contain a valid contract address
    
    await send_token_info(update, context, message_text)

async def send_token_info(update: Update, context: ContextTypes.DEFAULT_TYPE, contract_address: str) -> None:
    info_data = await get_dexscreener_token_info(contract_address)
    
    if info_data and 'pairs' in info_data and info_data['pairs']:
        info = info_data['pairs'][0]
        chain_name = html.escape(info.get('chainId', 'N/A').capitalize())
        base_token = info.get('baseToken', {})
        quote_token = info.get('quoteToken', {})
        market_data = info.get('priceChange', {})
        liquidity = info.get('liquidity', {})
        volume_24h = format_number(info.get('volume', {}).get('h24', 'N/A'))
        fdv = format_number(info.get('fdv', 'N/A'))
        txns = info.get('txns', {})
        pair_created_at = info.get('pairCreatedAt', 0)
        chart_url = html.escape(info.get('url', ''))

        buys_5m = html.escape(str(txns.get('m5', {}).get('buys', 'N/A')))
        sells_5m = html.escape(str(txns.get('m5', {}).get('sells', 'N/A')))
        buys_1h = html.escape(str(txns.get('h1', {}).get('buys', 'N/A')))
        sells_1h = html.escape(str(txns.get('h1', {}).get('sells', 'N/A')))
        buys_24h = html.escape(str(txns.get('h24', {}).get('buys', 'N/A')))
        sells_24h = html.escape(str(txns.get('h24', {}).get('sells', 'N/A')))
        
        token_symbol = html.escape(base_token.get('symbol', 'N/A'))
        
        price_change_1h = market_data.get('h1', 0.0)
        price_change_6h = market_data.get('h6', 0.0)
        price_change_24h = market_data.get('h24', 0.0)
        
        pair_age = html.escape(calculate_age(pair_created_at))

        dextools_url = f"https://www.dextools.io/app/{chain_name.lower()}/pair-explorer/{contract_address}"
        solscan_url = f"https://solscan.io/token/{contract_address}"

        response_message = (
            f"<b>Network:</b> {chain_name}\n"
            f"\n"
            f"<b>Token Name:</b> {html.escape(base_token.get('name', 'N/A'))}\n"
            f"<b>Symbol:</b> {token_symbol}\n"
            f"<b>Current Price (USD):</b> ${html.escape(str(info.get('priceUsd', 'N/A')))}\n"
            f"<b>Market Cap (USD):</b> ${fdv}\n"
            f"<b>Liquidity (USD):</b> ${format_number(liquidity.get('usd'))}\n"
            f"<b>Age:</b> {pair_age}\n"
            f"\n"
            f"<b>Buys/Sells (5m):</b> {buys_5m}/{sells_5m}\n"
            f"<b>Buys/Sells (1h):</b> {buys_1h}/{sells_1h}\n"
            f"<b>Buys/Sells (24h):</b> {buys_24h}/{sells_24h}\n"
            f"<b>24h Volume (USD):</b> ${volume_24h}\n"
            f"\n"
            f"<b>Price Change (1h):</b> {format_price_change(price_change_1h)}\n"
            f"<b>Price Change (6h):</b> {format_price_change(price_change_6h)}\n"
            f"<b>Price Change (24h):</b> {format_price_change(price_change_24h)}\n"
            f"\n"
            f"<a href='https://t.me/share/url?url={contract_address}'><code>{contract_address}</code></a>"
            f"\n"
            f"\n"
            f"<a href='{chart_url}'><b>Dexscreener</b></a> | "
            f"<a href='{dextools_url}'><b>DexTools</b></a> | "
            f"<a href='{solscan_url}'><b>Solscan</b></a>\n"
        )
        # Create the inline keyboard
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("Refresh Data", callback_data=contract_address)]]
        )
    else:
        response_message = "Unknown contract address or unavailable at this time."
        keyboard = None

    await update.message.reply_text(response_message, parse_mode=ParseMode.HTML, disable_web_page_preview=True, reply_markup=keyboard)

async def refresh_data(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    contract_address = query.data

    # Edit the message to indicate refreshing data
    refreshing_message = await query.edit_message_text("Refreshing data...", parse_mode=ParseMode.HTML)
    
    # Send the updated token information
    await send_token_info(query, context, contract_address)
    
    # Delete the "Refreshing data..." message
    try:
        await context.bot.delete_message(chat_id=refreshing_message.chat_id, message_id=refreshing_message.message_id)
    except Exception as e:
        logger.error(f"Failed to delete the refreshing message: {e}")

def main() -> None:
    """Start the bot."""
    # Load the token from the environment variable
    token = os.getenv('TELEGRAM_BOT_API_TOKEN')

    # Create the Application and pass it your bot's token.
    application = Application.builder().token(token).build()

    # Handle messages that are contract addresses or mention the bot
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Handle the callback for refreshing data
    application.add_handler(CallbackQueryHandler(refresh_data))

    # Start the Bot
    application.run_polling()

if __name__ == '__main__':
    main()
