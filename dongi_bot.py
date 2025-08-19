# dongi_bot.py (نسخه نهایی با اصلاح NameError)
import logging
import os
from functools import wraps
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ConversationHandler,
)
from telegram.error import Forbidden

print("--- STARTING FINAL BOT VERSION WITH ADMIN FEATURES ---")

# --- تنظیمات ادمین ---
ADMIN_CHAT_ID = 609782275 # !!! این قسمت را با آیدی تلگرام خودتان جایگزین کنید !!!

# --- تنظیمات اولیه ---
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# --- تنظیمات پایگاه داده ---
from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean
from sqlalchemy.orm import sessionmaker, declarative_base

Base = declarative_base()

class Person(Base):
    __tablename__ = 'people'
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)

class Expense(Base):
    __tablename__ = 'expenses'
    id = Column(Integer, primary_key=True)
    payer_name = Column(String, nullable=False)
    amount = Column(Float, nullable=False)
    description = Column(String)

class User(Base):
    __tablename__ = 'users'
    chat_id = Column(Integer, primary_key=True, unique=True)
    is_blocked = Column(Boolean, default=False, nullable=False)

engine = create_engine('sqlite:////data/dongi.db')
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)
session = Session()

# --- متغیرهای حالت برای فرآیند ثبت هزینه ---
SELECTING_PAYER, ENTERING_AMOUNT, ENTERING_DESC = range(3)

# --- دکوریتورها برای کنترل دسترسی ---
def check_if_blocked(func):
    @wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        chat_id = update.effective_chat.id
        user = session.query(User).filter_by(chat_id=chat_id).first()
        if user and user.is_blocked:
            logger.warning(f"Blocked user {chat_id} tried to use the bot.")
            return
        return await func(update, context, *args, **kwargs)
    return wrapped

def admin_only(func):
    @wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        chat_id = update.effective_chat.id
        if chat_id != ADMIN_CHAT_ID:
            await update.message.reply_text("شما اجازه دسترسی به این دستور را ندارید.")
            logger.warning(f"Unauthorized access attempt by {chat_id}.")
            return
        return await func(update, context, *args, **kwargs)
    return wrapped

# --- توابع ساخت دکمه‌های کیبوردی ---
def main_menu_reply_keyboard():
    keyboard = [
        ["💳 ثبت هزینه جدید", "📊 گزارش کامل"],
        ["🧾 لیست هزینه‌ها", "🗑️ حذف یک هزینه"],
        ["👥 مدیریت افراد"],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# --- دستورات اصلی ربات (با کنترل دسترسی) ---
@check_if_blocked
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat_id = update.effective_chat.id
    if not session.query(User).filter_by(chat_id=chat_id).first():
        new_user = User(chat_id=chat_id, is_blocked=False)
        session.add(new_user)
        session.commit()
    initial_people = ['حسین', 'علی', 'پویا']
    for name in initial_people:
        if not session.query(Person).filter_by(name=name).first():
            new_person = Person(name=name)
            session.add(new_person)
    session.commit()
    await update.message.reply_html(f'سلام {user.first_name}! 👋', reply_markup=main_menu_reply_keyboard())

@check_if_blocked
async def add_expense_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    target_message = update.message
    people = session.query(Person).all()
    if not people:
        await target_message.reply_text('هیچ فردی در لیست وجود ندارد!')
        return ConversationHandler.END
    keyboard = [[InlineKeyboardButton(person.name, callback_data=person.name)] for person in people]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await target_message.reply_text('چه کسی هزینه کرده؟', reply_markup=reply_markup)
    return SELECTING_PAYER

async def select_payer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    payer_name = query.data
    context.user_data['payer_name'] = payer_name
    await query.edit_message_text(text=f"پرداخت کننده: {payer_name}\n\nحالا مبلغ هزینه را به تومان وارد کن:")
    return ENTERING_AMOUNT

async def enter_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        amount = float(update.message.text)
        context.user_data['amount'] = amount
        await update.message.reply_text('عالی! حالا یک توضیح کوتاه برای هزینه بنویس (مثلا: شام):')
        return ENTERING_DESC
    except ValueError:
        await update.message.reply_text('لطفاً یک عدد معتبر برای مبلغ وارد کن.')
        return ENTERING_AMOUNT

async def enter_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    description = update.message.text
    payer_name = context.user_data['payer_name']
    amount = context.user_data['amount']
    new_expense = Expense(payer_name=payer_name, amount=amount, description=description)
    session.add(new_expense)
    session.commit()
    await update.message.reply_text(f"✅ هزینه ثبت شد.", reply_markup=main_menu_reply_keyboard())
    notification_message = f"📢 هزینه جدید توسط {update.effective_user.first_name} ثبت شد:\nپرداخت کننده: {payer_name}\nمبلغ: {amount:,.0f} تومان\nبابت: {description}"
    await send_notification_to_all(notification_message, context, notifier_chat_id=update.effective_chat.id)
    context.user_data.clear()
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text('عملیات لغو شد.', reply_markup=main_menu_reply_keyboard())
    context.user_data.clear()
    return ConversationHandler.END

@check_if_blocked
async def report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    people = session.query(Person).all()
    if not people: await update.message.reply_text('هنوز فردی اضافه نشده.'); return
    expenses = session.query(Expense).all()
    if not expenses: await update.message.reply_text('هنوز هزینه‌ای ثبت نشده.'); return
    report_text = '📊 <b>گزارش کامل دنگ‌ها</b> 📊\n\n'
    total_spent = 0
    individual_totals = {person.name: 0 for person in people}
    for expense in expenses:
        if expense.payer_name in individual_totals: individual_totals[expense.payer_name] += expense.amount
        total_spent += expense.amount
    report_text += '<b>جمع هزینه‌های هر فرد:</b>\n'
    for name, total in sorted(individual_totals.items(), key=lambda item: item[1], reverse=True):
        report_text += f'- <i>{name}</i>: {total:,.0f} تومان\n'
    report_text += f'\n💰 <b>مجموع کل هزینه‌ها:</b> {total_spent:,.0f} تومان\n'
    if individual_totals:
        min_spender = min(individual_totals, key=individual_totals.get)
        report_text += f'\n👇 <b>نفر بعدی برای پرداخت:</b>\n<i>{min_spender}</i>'
    await update.message.reply_html(report_text, reply_markup=main_menu_reply_keyboard())

@check_if_blocked
async def my_expenses(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    all_expenses = session.query(Expense).order_by(Expense.id).all()
    if not all_expenses: await update.message.reply_text("هنوز هیچ هزینه‌ای ثبت نشده."); return
    response_text = "<b>لیست تمام هزینه‌های ثبت شده:</b>\n\n"
    for exp in all_expenses:
        response_text += f"<code>ID: {exp.id}</code> | {exp.payer_name} | {exp.amount:,.0f} | {exp.description}\n"
    response_text += "\nبرای حذف، از دستور <code>/delete ID</code> استفاده کنید."
    await update.message.reply_html(response_text, reply_markup=main_menu_reply_keyboard())
    
@check_if_blocked
async def manage_people_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("برای مدیریت افراد از دستورات زیر استفاده کنید:\n`/addperson <اسم>`\n`/delperson <اسم>`", reply_markup=main_menu_reply_keyboard())

@check_if_blocked
async def delete_expense_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_html("برای حذف، ابتدا با دکمه '🧾 لیست هزینه‌ها'، ID را پیدا کرده و سپس از دستور زیر استفاده کنید:\n<code>/delete ID</code>", reply_markup=main_menu_reply_keyboard())

async def send_notification_to_all(message: str, context: ContextTypes.DEFAULT_TYPE, notifier_chat_id: int):
    all_users = session.query(User).all()
    for user in all_users:
        if user.chat_id == notifier_chat_id: continue
        try:
            await context.bot.send_message(chat_id=user.chat_id, text=message)
        except Forbidden:
            logger.warning(f"User {user.chat_id} has blocked the bot. Removing from DB.")
            session.delete(user)
            session.commit()
        except Exception as e:
            logger.error(f"Could not send message to {user.chat_id}: {e}")

@check_if_blocked
async def add_person(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args: await update.message.reply_text('مثال: /addperson رضا'); return
    new_name = context.args[0]
    if session.query(Person).filter_by(name=new_name).first(): await update.message.reply_text(f'"{new_name}" از قبل موجود است.'); return
    new_person = Person(name=new_name); session.add(new_person); session.commit()
    await update.message.reply_text(f'✅ فرد جدید "{new_name}" اضافه شد.')

@check_if_blocked
async def del_person(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args: await update.message.reply_text('مثال: /delperson علی'); return
    name_to_delete = context.args[0]
    person = session.query(Person).filter_by(name=name_to_delete).first()
    if person:
        session.delete(person); session.commit()
        await update.message.reply_text(f'🗑️ "{name_to_delete}" از لیست حذف شد.')
    else: await update.message.reply_text(f'فردی با نام "{name_to_delete}" پیدا نشد.')
        
@check_if_blocked
async def delete_expense(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args: await update.message.reply_text('مثال: /delete 12'); return
    try:
        expense_id = int(context.args[0])
        expense_to_delete = session.query(Expense).filter_by(id=expense_id).first()
        if expense_to_delete:
            deleted_info = f"ID: {expense_to_delete.id}, پرداخت‌کننده: {expense_to_delete.payer_name}, مبلغ: {expense_to_delete.amount:,.0f}"
            session.delete(expense_to_delete); session.commit()
            await update.message.reply_html(f'✅ هزینه با <code>ID {expense_id}</code> حذف شد.')
            notification_message = f"🗑️ یک هزینه توسط {update.effective_user.first_name} حذف شد:\n{deleted_info}"
            await send_notification_to_all(notification_message, context, notifier_chat_id=update.effective_chat.id)
        else: await update.message.reply_text('هزینه‌ای با این ID پیدا نشد.')
    except ValueError: await update.message.reply_text('ID باید یک عدد باشد.')

@admin_only
async def list_users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    all_users = session.query(User).all()
    if not all_users: await update.message.reply_text("هیچ کاربری یافت نشد."); return
    message = "لیست کاربران ربات:\n\n"
    for user in all_users:
        status = "❌ بلاک شده" if user.is_blocked else "✅ فعال"
        message += f"<b>Chat ID:</b> <code>{user.chat_id}</code> - {status}\n"
    await update.message.reply_html(message)

@admin_only
async def block_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        chat_id_to_block = int(context.args[0])
        user = session.query(User).filter_by(chat_id=chat_id_to_block).first()
        if user:
            user.is_blocked = True; session.commit()
            await update.message.reply_text(f"کاربر {chat_id_to_block} بلاک شد.")
        else: await update.message.reply_text("کاربر یافت نشد.")
    except (IndexError, ValueError): await update.message.reply_text("مثال: /block 987654321")

@admin_only
async def unblock_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        chat_id_to_unblock = int(context.args[0])
        user = session.query(User).filter_by(chat_id=chat_id_to_unblock).first()
        if user:
            user.is_blocked = False; session.commit()
            await update.message.reply_text(f"کاربر {chat_id_to_unblock} آنبلاک شد.")
        else: await update.message.reply_text("کاربر یافت نشد.")
    except (IndexError, ValueError): await update.message.reply_text("مثال: /unblock 987654321")

def main() -> None:
    TOKEN = os.environ.get("TELEGRAM_TOKEN")
    if not TOKEN: print("خطا: توکن تلگرام یافت نشد."); return
    application = Application.builder().token(TOKEN).build()
    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('^💳 ثبت هزینه جدید$'), add_expense_start)],
        states={
            SELECTING_PAYER: [CallbackQueryHandler(select_payer)],
            ENTERING_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_amount)],
            ENTERING_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_description)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )
    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv_handler)
    application.add_handler(MessageHandler(filters.Regex('^📊 گزارش کامل$'), report))
    application.add_handler(MessageHandler(filters.Regex('^🧾 لیست هزینه‌ها$'), my_expenses))
    application.add_handler(MessageHandler(filters.Regex('^👥 مدیریت افراد$'), manage_people_prompt))
    application.add_handler(MessageHandler(filters.Regex('^🗑️ حذف یک هزینه$'), delete_expense_prompt))
    application.add_handler(CommandHandler("addperson", add_person))
    application.add_handler(CommandHandler("delperson", del_person))
    application.add_handler(CommandHandler("delete", delete_expense))
    application.add_handler(CommandHandler("listusers", list_users))
    application.add_handler(CommandHandler("block", block_user))
    application.add_handler(CommandHandler("unblock", unblock_user))
    print("ربات با موفقیت در حال اجراست...")
    application.run_polling()

if __name__ == '__main__':
    main()