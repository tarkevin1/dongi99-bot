# dongi_bot.py (نسخه نهایی برای دیپلوی)
import logging
import os  # <-- این خط برای خواندن توکن اضافه شده
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, constants
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ConversationHandler,
)

# --- تنظیمات اولیه برای نمایش لاگ‌ها ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- تنظیمات پایگاه داده با SQLAlchemy ---
from sqlalchemy import create_engine, Column, Integer, String, Float
from sqlalchemy.orm import sessionmaker, declarative_base

Base = declarative_base()

# جدول افراد
class Person(Base):
    __tablename__ = 'people'
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)

# جدول هزینه‌ها
class Expense(Base):
    __tablename__ = 'expenses'
    id = Column(Integer, primary_key=True)
    payer_name = Column(String, nullable=False)
    amount = Column(Float, nullable=False)
    description = Column(String)

# ایجاد و اتصال به پایگاه داده
# نکته: در Railway، این فایل دیتابیس با هر بار آپدیت ریست می‌شود. برای ذخیره دائمی باید از دیتابیس‌های ابری استفاده کرد.
engine = create_engine('sqlite:///dongi.db')
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)
session = Session()

# --- متغیرهای حالت برای مکالمه چندمرحله‌ای ---
SELECTING_PAYER, ENTERING_AMOUNT, ENTERING_DESC = range(3)

# --- تعریف دستورات ربات ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """دستور /start که ربات را معرفی و افراد اولیه را اضافه می‌کند."""
    user = update.effective_user
    initial_people = ['حسین', 'علی', 'پویا']
    for name in initial_people:
        if not session.query(Person).filter_by(name=name).first():
            new_person = Person(name=name)
            session.add(new_person)
    session.commit()
    
    await update.message.reply_html(
        f'سلام {user.first_name}! 👋\n'
        'من ربات مدیریت دنگ شما هستم.\n\n'
        'از دستورات زیر استفاده کن:\n'
        '<b>/add</b> - ثبت هزینه جدید\n'
        '<b>/report</b> - نمایش گزارش کامل دنگ‌ها\n'
        '<b>/myexpenses</b> - نمایش هزینه‌های ثبت شده\n'
        '<b>/delete &lt;id&gt;</b> - حذف یک هزینه با شماره ID\n'
        '<b>/addperson &lt;اسم&gt;</b> - اضافه کردن فرد جدید\n'
        '<b>/delperson &lt;اسم&gt;</b> - حذف یک فرد\n'
        '<b>/help</b> - نمایش همین راهنما',
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """دستور /help که راهنمای دستورات را نمایش می‌دهد."""
    await update.message.reply_html(
        '<b>راهنمای دستورات:</b>\n\n'
        '<b>/add</b> - برای ثبت یک هزینه جدید.\n\n'
        '<b>/report</b> - گزارش کاملی از هزینه‌ها و پیشنهاد نفر بعدی برای پرداخت.\n\n'
        '<b>/myexpenses</b> - لیست تمام هزینه‌های ثبت شده با ID.\n\n'
        '<b>/delete &lt;ID&gt;</b> - حذف یک هزینه با ID. (مثال: /delete 12)\n\n'
        '<b>/addperson &lt;اسم&gt;</b> - اضافه کردن دوست جدید. (مثال: /addperson رضا)\n\n'
        '<b>/delperson &lt;اسم&gt;</b> - حذف یک نفر. (مثال: /delperson علی)\n'
    )

async def add_expense_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """شروع فرآیند ثبت هزینه با دستور /add."""
    people = session.query(Person).all()
    if not people:
        await update.message.reply_text('هیچ فردی در لیست وجود ندارد! ابتدا با /addperson یک نفر را اضافه کنید.')
        return ConversationHandler.END

    keyboard = [[InlineKeyboardButton(person.name, callback_data=person.name)] for person in people]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text('چه کسی هزینه کرده؟', reply_markup=reply_markup)
    return SELECTING_PAYER

async def select_payer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """مرحله ۱: انتخاب پرداخت کننده."""
    query = update.callback_query
    await query.answer()
    payer_name = query.data
    context.user_data['payer_name'] = payer_name
    await query.edit_message_text(text=f"پرداخت کننده: {payer_name}\n\nحالا مبلغ هزینه را به تومان وارد کن:")
    return ENTERING_AMOUNT

async def enter_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """مرحله ۲: دریافت مبلغ."""
    try:
        amount = float(update.message.text)
        context.user_data['amount'] = amount
        await update.message.reply_text('عالی! حالا یک توضیح کوتاه برای هزینه بنویس (مثلا: شام):')
        return ENTERING_DESC
    except ValueError:
        await update.message.reply_text('لطفاً یک عدد معتبر برای مبلغ وارد کن.')
        return ENTERING_AMOUNT

async def enter_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """مرحله ۳: دریافت توضیحات و ذخیره هزینه."""
    description = update.message.text
    payer_name = context.user_data['payer_name']
    amount = context.user_data['amount']

    new_expense = Expense(payer_name=payer_name, amount=amount, description=description)
    session.add(new_expense)
    session.commit()

    await update.message.reply_text(f"✅ هزینه ثبت شد:\nپرداخت کننده: {payer_name}\nمبلغ: {amount:,.0f} تومان\nبابت: {description}")
    
    context.user_data.clear()
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """لغو فرآیند ثبت هزینه."""
    await update.message.reply_text('عملیات ثبت هزینه لغو شد.')
    context.user_data.clear()
    return ConversationHandler.END

async def report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """نمایش گزارش کامل هزینه‌ها."""
    people = session.query(Person).all()
    if not people:
        await update.message.reply_text('هنوز فردی اضافه نشده است.')
        return
    
    expenses = session.query(Expense).all()
    if not expenses:
        await update.message.reply_text('هنوز هزینه‌ای ثبت نشده است.')
        return

    report_text = '📊 <b>گزارش کامل دنگ‌ها</b> 📊\n\n'
    total_spent = 0
    individual_totals = {person.name: 0 for person in people}

    for expense in expenses:
        if expense.payer_name in individual_totals:
            individual_totals[expense.payer_name] += expense.amount
        total_spent += expense.amount

    report_text += '<b>جمع هزینه‌های هر فرد:</b>\n'
    for name, total in sorted(individual_totals.items(), key=lambda item: item[1], reverse=True):
        report_text += f'- <i>{name}</i>: {total:,.0f} تومان\n'

    report_text += f'\n💰 <b>مجموع کل هزینه‌ها:</b> {total_spent:,.0f} تومان\n'

    if individual_totals:
        min_spender = min(individual_totals, key=individual_totals.get)
        report_text += f'\n👇 <b>نفر بعدی برای پرداخت:</b>\n<i>{min_spender}</i> (کمترین هزینه را داشته است)'
    
    await update.message.reply_html(report_text)

async def add_person(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """افزودن فرد جدید."""
    if not context.args:
        await update.message.reply_text('لطفاً اسم فرد را بعد از دستور وارد کن.\nمثال: /addperson رضا')
        return
    
    new_name = context.args[0]
    if session.query(Person).filter_by(name=new_name).first():
        await update.message.reply_text(f'"{new_name}" از قبل در لیست وجود دارد.')
    else:
        new_person = Person(name=new_name)
        session.add(new_person)
        session.commit()
        await update.message.reply_text(f'✅ فرد جدید "{new_name}" اضافه شد.')

async def del_person(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """حذف یک فرد."""
    if not context.args:
        await update.message.reply_text('لطفاً اسم فرد را بعد از دستور وارد کن.\nمثال: /delperson علی')
        return

    name_to_delete = context.args[0]
    person = session.query(Person).filter_by(name=name_to_delete).first()
    if person:
        session.delete(person)
        session.commit()
        await update.message.reply_text(f'🗑️ "{name_to_delete}" از لیست حذف شد.')
    else:
        await update.message.reply_text(f'فردی با نام "{name_to_delete}" پیدا نشد.')

async def my_expenses(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """نمایش تمام هزینه‌های ثبت‌شده با ID."""
    all_expenses = session.query(Expense).order_by(Expense.id).all()
    if not all_expenses:
        await update.message.reply_text("هنوز هیچ هزینه‌ای ثبت نشده است.")
        return
            
    response_text = "<b>لیست تمام هزینه‌های ثبت شده:</b>\n\n"
    for exp in all_expenses:
        response_text += f"<code>ID: {exp.id}</code> | پرداخت کننده: {exp.payer_name} | مبلغ: {exp.amount:,.0f} | بابت: {exp.description}\n"
    
    response_text += "\nبرای حذف، از دستور <code>/delete ID</code> استفاده کنید."
    await update.message.reply_html(response_text)

async def delete_expense(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """حذف یک هزینه با ID مشخص."""
    if not context.args:
        await update.message.reply_text('لطفاً ID هزینه را بعد از دستور وارد کن.\nمثال: /delete 12')
        return
    try:
        expense_id = int(context.args[0])
        expense_to_delete = session.query(Expense).filter_by(id=expense_id).first()
        if expense_to_delete:
            session.delete(expense_to_delete)
            session.commit()
            await update.message.reply_html(f'✅ هزینه با <code>ID {expense_id}</code> با موفقیت حذف شد.')
        else:
            await update.message.reply_text('هزینه‌ای با این ID پیدا نشد.')
    except ValueError:
        await update.message.reply_text('ID باید یک عدد باشد.')

def main() -> None:
    """تابع اصلی برای ساخت و اجرای ربات."""
    # توکن ربات از متغیرهای محیطی خوانده می‌شود
    TOKEN = os.environ.get("TELEGRAM_TOKEN")
    if not TOKEN:
        print("خطا: توکن تلگرام پیدا نشد. لطفاً متغیر محیطی TELEGRAM_TOKEN را تنظیم کنید.")
        return

    application = Application.builder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('add', add_expense_start)],
        states={
            SELECTING_PAYER: [CallbackQueryHandler(select_payer)],
            ENTERING_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_amount)],
            ENTERING_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_description)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("report", report))
    application.add_handler(CommandHandler("addperson", add_person))
    application.add_handler(CommandHandler("delperson", del_person))
    application.add_handler(CommandHandler("myexpenses", my_expenses))
    application.add_handler(CommandHandler("delete", delete_expense))

    print("ربات در حال اجراست...")
    application.run_polling()

if __name__ == '__main__':
    main()