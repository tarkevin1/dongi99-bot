# dongi_bot.py (نسخه جدید با منوی کیبوردی)
import logging
import os
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup, constants
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ConversationHandler,
)

# --- تنظیمات اولیه ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- تنظیمات پایگاه داده ---
from sqlalchemy import create_engine, Column, Integer, String, Float
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

engine = create_engine('sqlite:////data/dongi.db')
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)
session = Session()

# --- متغیرهای حالت ---
SELECTING_PAYER, ENTERING_AMOUNT, ENTERING_DESC = range(3)

# --- تابع ساخت دکمه‌های کیبوردی (جدید) ---
def main_menu_reply_keyboard():
    # تعریف دکمه‌ها در ردیف‌های مختلف
    keyboard = [
        ["💳 ثبت هزینه جدید", "📊 گزارش کامل"],
        ["🧾 لیست هزینه‌ها", "👥 مدیریت افراد"],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# --- دستورات و توابع اصلی ربات ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    initial_people = ['حسین', 'علی', 'پویا']
    for name in initial_people:
        if not session.query(Person).filter_by(name=name).first():
            new_person = Person(name=name)
            session.add(new_person)
    session.commit()
    
    # ارسال پیام خوش‌آمدگویی به همراه کیبورد جدید
    await update.message.reply_html(
        f'سلام {user.first_name}! 👋\n'
        'به ربات مدیریت دنگ خوش آمدی. لطفاً از منوی زیر استفاده کن.',
        reply_markup=main_menu_reply_keyboard()
    )

# --- توابع مربوط به فرآیند ثبت هزینه ---
# این بخش از دکمه‌های شیشه‌ای استفاده می‌کند که برای این کار مناسب‌تر است
async def add_expense_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    target_message = update.message
    people = session.query(Person).all()
    if not people:
        await target_message.reply_text('هیچ فردی در لیست وجود ندارد! ابتدا با دستور /addperson یک نفر را اضافه کنید.')
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
    await update.message.reply_text(f"✅ هزینه ثبت شد:\nپرداخت کننده: {payer_name}\nمبلغ: {amount:,.0f} تومان\nبابت: {description}", reply_markup=main_menu_reply_keyboard())
    context.user_data.clear()
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text('عملیات ثبت هزینه لغو شد.', reply_markup=main_menu_reply_keyboard())
    context.user_data.clear()
    return ConversationHandler.END

# --- توابع اصلی که با دکمه‌ها فراخوانی می‌شوند ---
async def report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # ... (کد تابع report بدون تغییر) ...
    people = session.query(Person).all()
    if not people: await update.message.reply_text('...'); return
    expenses = session.query(Expense).all()
    if not expenses: await update.message.reply_text('...'); return
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
    await update.message.reply_html(report_text, reply_markup=main_menu_reply_keyboard())

async def my_expenses(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # ... (کد تابع my_expenses بدون تغییر) ...
    all_expenses = session.query(Expense).order_by(Expense.id).all()
    if not all_expenses:
        await update.message.reply_text("هنوز هیچ هزینه‌ای ثبت نشده است.", reply_markup=main_menu_reply_keyboard())
        return
    response_text = "<b>لیست تمام هزینه‌های ثبت شده:</b>\n\n"
    for exp in all_expenses:
        response_text += f"<code>ID: {exp.id}</code> | {exp.payer_name} | {exp.amount:,.0f} | {exp.description}\n"
    response_text += "\nبرای حذف، از دستور <code>/delete ID</code> استفاده کنید."
    await update.message.reply_html(response_text, reply_markup=main_menu_reply_keyboard())
    
async def manage_people_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """راهنمایی برای مدیریت افراد"""
    await update.message.reply_text(
        "برای مدیریت افراد از دستورات زیر استفاده کنید:\n\n"
        "▫️ افزودن: `/addperson <اسم>`\n"
        "▫️ حذف: `/delperson <اسم>`",
        reply_markup=main_menu_reply_keyboard()
    )

# --- توابع مدیریت دستورات متنی ---
async def add_person(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None: # بدون تغییر
    # ... (کد تابع add_person) ...
    if not context.args: await update.message.reply_text('...'); return
    new_name = context.args[0]
    if session.query(Person).filter_by(name=new_name).first():
        await update.message.reply_text(f'"{new_name}" از قبل موجود است.')
    else:
        new_person = Person(name=new_name)
        session.add(new_person)
        session.commit()
        await update.message.reply_text(f'✅ فرد جدید "{new_name}" اضافه شد.')

async def del_person(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None: # بدون تغییر
    # ... (کد تابع del_person) ...
    if not context.args: await update.message.reply_text('...'); return
    name_to_delete = context.args[0]
    person = session.query(Person).filter_by(name=name_to_delete).first()
    if person:
        session.delete(person)
        session.commit()
        await update.message.reply_text(f'🗑️ "{name_to_delete}" از لیست حذف شد.')
    else:
        await update.message.reply_text(f'فردی با نام "{name_to_delete}" پیدا نشد.')
        
async def delete_expense(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None: # بدون تغییر
    # ... (کد تابع delete_expense) ...
    if not context.args: await update.message.reply_text('...'); return
    try:
        expense_id = int(context.args[0])
        expense_to_delete = session.query(Expense).filter_by(id=expense_id).first()
        if expense_to_delete:
            session.delete(expense_to_delete)
            session.commit()
            await update.message.reply_html(f'✅ هزینه با <code>ID {expense_id}</code> حذف شد.')
        else:
            await update.message.reply_text('هزینه‌ای با این ID پیدا نشد.')
    except ValueError:
        await update.message.reply_text('ID باید یک عدد باشد.')

def main() -> None:
    TOKEN = os.environ.get("TELEGRAM_TOKEN")
    if not TOKEN:
        print("خطا: توکن تلگرام پیدا نشد.")
        return

    application = Application.builder().token(TOKEN).build()

    # ConversationHandler برای ثبت هزینه (بدون تغییر)
    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('^💳 ثبت هزینه جدید$'), add_expense_start)],
        states={
            SELECTING_PAYER: [CallbackQueryHandler(select_payer)],
            ENTERING_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_amount)],
            ENTERING_DESC: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_description)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )

    # افزودن دستورات و مدیریت دکمه‌های کیبوردی
    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv_handler)
    
    # مدیریت کلیک روی دکمه‌های کیبوردی
    application.add_handler(MessageHandler(filters.Regex('^📊 گزارش کامل$'), report))
    application.add_handler(MessageHandler(filters.Regex('^🧾 لیست هزینه‌ها$'), my_expenses))
    application.add_handler(MessageHandler(filters.Regex('^👥 مدیریت افراد$'), manage_people_prompt))

    # دستورات متنی هنوز برای دسترسی مستقیم فعال هستند
    application.add_handler(CommandHandler("addperson", add_person))
    application.add_handler(CommandHandler("delperson", del_person))
    application.add_handler(CommandHandler("delete", delete_expense))

    print("ربات در حال اجراست...")
    application.run_polling()

if __name__ == '__main__':
    main()