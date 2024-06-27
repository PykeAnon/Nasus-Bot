import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember
from telegram.constants import ParseMode
from telegram.ext import Application, MessageHandler, CallbackQueryHandler, filters, ContextTypes
import httpx
from dotenv import load_dotenv
import os
import base58
from datetime import datetime, timezone
import html
from collections import defaultdict

load_dotenv()

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

logger = logging.getLogger(__name__)

DEXSCREENER_API_URL = "https://api.dexscreener.com/latest/dex/search/?q="
PUMPFUN_API_URL = "https://frontend-api.pump.fun/coins/"

# Dictionary to store tracked contracts and their initial market caps
tracked_contracts = defaultdict(lambda: {"initial_market_cap": None, "last_alerted_cap": None, "pin_message_id": None, "chat_id": None})

def is_valid_base58(address: str) -> bool:
    if len(address) in range(32, 45):
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

async def get_pumpfun_token_info(contract_address: str) -> dict:
    url = f"{PUMPFUN_API_URL}{contract_address}"
    return await fetch_data(url)

def format_price_change(change: float) -> str:
    return f"🟢{change:.2f}%" if change > 0 else f"🔴{change:.2f}%" if change < 0 else f"{change:.2f}%"

def format_number(number, is_buy_sell=False) -> str:
    try:
        number = float(number)
        if is_buy_sell and number < 1000:
            return f"{int(number)}"
        elif number >= 1_000_000_000:
            return f"{number / 1_000_000_000:.2f}B"
        elif number >= 1_000_000:
            return f"{number / 1_000_000:.2f}M"
        elif number >= 1_000:
            return f"{number / 1_000:.2f}K"
        else:
            return f"{number:.2f}"
    except (ValueError, TypeError):
        return 'N/A'

def calculate_age(pair_created_at: int) -> str:
    if pair_created_at:
        creation_date = datetime.fromtimestamp(pair_created_at / 1000, tz=timezone.utc)
        age = datetime.now(tz=timezone.utc) - creation_date
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

def safe_html_escape(s: str) -> str:
    return html.escape(s or 'N/A')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message and update.message.text:
        message_text = update.message.text.strip()

        # Check if the message contains a valid contract address
        if not is_contract_address(message_text):
            return  # Ignore the message if it doesn't contain a valid contract address
        
        await send_token_info(update=update, context=context, contract_address=message_text)

async def send_token_info(update: Update, context: ContextTypes.DEFAULT_TYPE, contract_address: str, is_refresh=False, chat_id=None, message_id=None) -> None:
    info_data = await get_dexscreener_token_info(contract_address)
    
    if info_data and 'pairs' in info_data and info_data['pairs']:
        info = info_data['pairs'][0]
        chain_name = safe_html_escape(info.get('chainId', 'N/A').capitalize())
        base_token = info.get('baseToken', {})
        quote_token = info.get('quoteToken', {})
        market_data = info.get('priceChange', {})
        liquidity = info.get('liquidity', {})
        volume_5m = format_number(info.get('volume', {}).get('m5', 'N/A'))
        volume_1h = format_number(info.get('volume', {}).get('h1', 'N/A'))
        volume_24h = format_number(info.get('volume', {}).get('h24', 'N/A'))
        fdv = format_number(info.get('fdv', 'N/A'))
        txns = info.get('txns', {})
        pair_created_at = info.get('pairCreatedAt', 0)
        chart_url = safe_html_escape(info.get('url', ''))

        buys_5m = safe_html_escape(format_number(txns.get('m5', {}).get('buys', 'N/A'), is_buy_sell=True))
        sells_5m = safe_html_escape(format_number(txns.get('m5', {}).get('sells', 'N/A'), is_buy_sell=True))
        buys_1h = safe_html_escape(format_number(txns.get('h1', {}).get('buys', 'N/A'), is_buy_sell=True))
        sells_1h = safe_html_escape(format_number(txns.get('h1', {}).get('sells', 'N/A'), is_buy_sell=True))
        buys_24h = safe_html_escape(format_number(txns.get('h24', {}).get('buys', 'N/A'), is_buy_sell=True))
        sells_24h = safe_html_escape(format_number(txns.get('h24', {}).get('sells', 'N/A'), is_buy_sell=True))

        token_symbol = safe_html_escape(base_token.get('symbol', 'N/A'))
        
        price_change_1h = market_data.get('h1', 0.0)
        price_change_6h = market_data.get('h6', 0.0)
        price_change_24h = market_data.get('h24', 0.0)
        
        pair_age = safe_html_escape(calculate_age(pair_created_at))

        dextools_url = f"https://www.dextools.io/app/{chain_name.lower()}/pair-explorer/{contract_address}"
        solscan_url = f"https://solscan.io/token/{contract_address}"

        response_message = (
            f"<b>Network:</b> {chain_name}\n"
            f"\n"
            f"<b>{safe_html_escape(base_token.get('name', 'N/A'))}</b> | <b>${token_symbol}</b>\n\n"
            f"<b>💲 Price (USD):</b> ${safe_html_escape(str(info.get('priceUsd', 'N/A')))}\n"
            f"<b>💰 MC (USD):</b> ${fdv}\n"
            f"<b>💧 Liq (USD):</b> ${format_number(liquidity.get('usd'))}\n"
            f"<b>🕒 Age:</b> {pair_age}\n"
            f"\n"
            f"<b>🔄 B/S: 5m:</b> {buys_5m}/{sells_5m} | <b>1h:</b> {buys_1h}/{sells_1h} | <b>24h:</b> {buys_24h}/{sells_24h}\n"
            f"<b>📊 Volume (USD): 5m:</b> ${volume_5m} | <b>1h:</b> ${volume_1h} | <b>24h:</b> ${volume_24h}\n"
            f"\n"
            f"<b>📈 % Change: 1h:</b> {format_price_change(price_change_1h)} | <b>6h:</b> {format_price_change(price_change_6h)} | <b>24h:</b> {format_price_change(price_change_24h)}\n"
            f"\n"
            f"<a href='https://t.me/share/url?url={contract_address}'><code>{contract_address}</code></a>"
            f"\n"
            f"\n"
            f"<a href='{chart_url}'><b>Dexscreener</b></a> | "
            f"<a href='{dextools_url}'><b>DexTools</b></a> | "
            f"<a href='{solscan_url}'><b>Solscan</b></a>\n"
        )
        # Create the inline keyboard
        track_button_label = "✅ Track" if tracked_contracts[contract_address]["initial_market_cap"] else "❌ Track"
        keyboard = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("Refresh Data", callback_data=f"refresh_{contract_address}"),
                 InlineKeyboardButton(track_button_label, callback_data=f"toggle_{contract_address}")]
            ]
        )

        if is_refresh:
            await context.bot.edit_message_text(
                chat_id=chat_id, message_id=message_id, text="Refreshing data...",
                parse_mode=ParseMode.HTML
            )
            await asyncio.sleep(2)
            await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
            sent_message = await context.bot.send_message(
                chat_id=chat_id, text=response_message, parse_mode=ParseMode.HTML,
                disable_web_page_preview=True, reply_markup=keyboard
            )

            # Re-pin the message if the contract is being tracked
            if tracked_contracts[contract_address]["initial_market_cap"] is not None:
                await context.bot.pin_chat_message(chat_id=chat_id, message_id=sent_message.message_id)
                tracked_contracts[contract_address]["pin_message_id"] = sent_message.message_id

            return sent_message.message_id, chat_id
        else:
            sent_message = await update.message.reply_text(response_message, parse_mode=ParseMode.HTML, disable_web_page_preview=True, reply_markup=keyboard)
            return sent_message.message_id, update.message.chat_id
    else:
        # Try to fetch data from Pump.fun API
        pumpfun_data = await get_pumpfun_token_info(contract_address)
        if pumpfun_data:
            name = safe_html_escape(pumpfun_data.get('name', 'N/A'))
            mint = safe_html_escape(pumpfun_data.get('mint', 'N/A'))
            symbol = safe_html_escape(pumpfun_data.get('symbol', 'N/A'))
            description = safe_html_escape(pumpfun_data.get('description', 'N/A'))
            twitter = safe_html_escape(pumpfun_data.get('twitter', 'N/A'))
            telegram = safe_html_escape(pumpfun_data.get('telegram', 'N/A'))
            website = safe_html_escape(pumpfun_data.get('website', '') or 'N/A')
            market_cap = format_number(pumpfun_data.get('usd_market_cap', 'N/A'))
            pumpfun_url = f"https://pump.fun/{contract_address}"

            social_links = []
            if twitter != 'N/A':
                social_links.append(f"<a href='{twitter}'>Twitter</a>")
            if telegram != 'N/A':
                social_links.append(f"<a href='{telegram}'>Telegram</a>")
            if website != 'N/A':
                social_links.append(f"<a href='{website}'>Website</a>")
            social_links_str = " | ".join(social_links)

            response_message = (
                f"<b>{name}</b> | <b>${symbol}</b>\n\n"
                f"📝<b>Description:</b> {description}\n"
                f"💰<b>MC (USD):</b> ${market_cap}\n\n"
                f"🌐<b>Socials:</b> {social_links_str}\n\n"
                f"<code>{mint}</code>\n"
                f"\n"
                f"<a href='{pumpfun_url}'><b>Pump.fun</b></a>\n"
            )

            await update.message.reply_text(response_message, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        else:
            response_message = "Unknown contract address or unavailable at this time."
            await update.message.reply_text(response_message, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

async def refresh_data(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    contract_address = query.data.split('_')[1]

    # Refresh the data and delete the old message
    await send_token_info(update=query, context=context, contract_address=contract_address, is_refresh=True, chat_id=query.message.chat_id, message_id=query.message.message_id)

async def toggle_tracking(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    contract_address = query.data.split('_')[1]

    user_id = query.from_user.id
    chat_id = query.message.chat_id

    member = await context.bot.get_chat_member(chat_id, user_id)
    if member.status not in [ChatMember.ADMINISTRATOR, ChatMember.OWNER]:
        no_permission_message = await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="You do not have permission to add to the Track List.",
            parse_mode=ParseMode.HTML
        )
        await asyncio.sleep(10)
        await context.bot.delete_message(chat_id=no_permission_message.chat_id, message_id=no_permission_message.message_id)
        return

    if tracked_contracts[contract_address]["initial_market_cap"] is None:
        info_data = await get_dexscreener_token_info(contract_address)
        if info_data and 'pairs' in info_data and info_data['pairs']:
            market_cap = float(info_data['pairs'][0].get('fdv', 0))
            tracked_contracts[contract_address]["initial_market_cap"] = market_cap
            tracked_contracts[contract_address]["last_alerted_cap"] = market_cap
            tracked_contracts[contract_address]["pin_message_id"] = query.message.message_id
            tracked_contracts[contract_address]["chat_id"] = query.message.chat_id
            await context.bot.pin_chat_message(chat_id=query.message.chat_id, message_id=query.message.message_id)
            await query.edit_message_reply_markup(
                reply_markup=InlineKeyboardMarkup(
                    [
                        [InlineKeyboardButton("Refresh Data", callback_data=f"refresh_{contract_address}"),
                         InlineKeyboardButton("✅ Track", callback_data=f"toggle_{contract_address}")]
                    ]
                )
            )
    else:
        pin_message_id = tracked_contracts[contract_address]["pin_message_id"]
        chat_id = tracked_contracts[contract_address]["chat_id"]
        tracked_contracts[contract_address] = {"initial_market_cap": None, "last_alerted_cap": None, "pin_message_id": None, "chat_id": None}
        await context.bot.unpin_chat_message(chat_id=chat_id, message_id=pin_message_id)
        stop_message = await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"Stopped tracking {contract_address}.",
            parse_mode=ParseMode.HTML
        )
        await asyncio.sleep(5)
        await context.bot.delete_message(chat_id=stop_message.chat_id, message_id=stop_message.message_id)
        await query.edit_message_reply_markup(
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("Refresh Data", callback_data=f"refresh_{contract_address}"),
                     InlineKeyboardButton("❌ Track", callback_data=f"toggle_{contract_address}")]
                ]
            )
        )

async def check_tracked_contracts(context: ContextTypes.DEFAULT_TYPE) -> None:
    for contract_address, data in tracked_contracts.items():
        if data["initial_market_cap"] is None:
            continue

        info_data = await get_dexscreener_token_info(contract_address)
        if info_data and 'pairs' in info_data and info_data['pairs']:
            current_market_cap = float(info_data['pairs'][0].get('fdv', 0))
            initial_market_cap = data["initial_market_cap"]
            last_alerted_cap = data["last_alerted_cap"]

            # Price action condition changed to 1%
            if abs(current_market_cap - last_alerted_cap) / last_alerted_cap >= 0.05:
                direction = "up" if current_market_cap > last_alerted_cap else "down"
                percentage_change = ((current_market_cap - last_alerted_cap) / last_alerted_cap) * 100
                message = (
                    f"Market Cap Alert for <a href='https://t.me/share/url?url={contract_address}'>{contract_address}</a>: "
                    f"{direction} by {percentage_change:.2f}%"
                )
                await context.bot.send_message(chat_id=data["chat_id"], text=message, parse_mode=ParseMode.HTML)
                tracked_contracts[contract_address]["last_alerted_cap"] = current_market_cap

                # Unpin the old message and pin the new message only if the contract is being tracked
                await context.bot.unpin_chat_message(chat_id=data["chat_id"], message_id=data["pin_message_id"])
                pin_message_id, chat_id = await send_token_info(update=None, context=context, contract_address=contract_address, is_refresh=True, chat_id=data["chat_id"], message_id=data["pin_message_id"])
                if pin_message_id:
                    await context.bot.pin_chat_message(chat_id=chat_id, message_id=pin_message_id)
                    tracked_contracts[contract_address]["pin_message_id"] = pin_message_id

def main() -> None:
    """Start the bot."""
    try:
        
        token = os.getenv('TELEGRAM_BOT_API_TOKEN')

        if not token:
            logger.error("No TELEGRAM_BOT_API_TOKEN found in environment variables.")
            return

        # Create the Application and pass it your bot's token.
        application = Application.builder().token(token).build()

        # Handle messages that are contract addresses or mention the bot
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

        # callback for refreshing data
        application.add_handler(CallbackQueryHandler(refresh_data, pattern=r"refresh_"))

        # callback for tracking data
        application.add_handler(CallbackQueryHandler(toggle_tracking, pattern=r"toggle_"))

        # Schedule a job to check the tracked contracts periodically
        job_queue = application.job_queue
        job_queue.run_repeating(check_tracked_contracts, interval=30, first=10)

        application.run_polling()
    except Exception as e:
        logger.exception("An error occurred while starting the bot:")

if __name__ == '__main__':
    main()
