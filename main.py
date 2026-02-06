import os
import subprocess
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

TOKEN = os.getenv("BOT_TOKEN")
ADMIN = int(os.getenv("ADMIN_ID"))

FILES_DIR = "files"
os.makedirs(FILES_DIR, exist_ok=True)

running_processes = {}

keyboard = [
    ["📤 Upload File", "📁 Check Files"],
    ["🟢 My Running Bots", "📊 My Stats"],
    ["📞 Contact Owner"]
]

markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔥 Welcome to M7S TELI BOT HOSTING\n\nUpload and run your Telegram bots.",
        reply_markup=markup
    )


async def upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if not doc:
        return

    if not doc.file_name.endswith((".py", ".js", ".zip")):
        await update.message.reply_text("❌ Only .py .js .zip allowed.")
        return

    path = os.path.join(FILES_DIR, doc.file_name)
    file = await doc.get_file()
    await file.download_to_drive(path)

    await update.message.reply_text(f"✅ Uploaded: {doc.file_name}")


async def check_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    files = os.listdir(FILES_DIR)

    if not files:
        await update.message.reply_text("No files uploaded.")
        return

    await update.message.reply_text("\n".join(files))


async def run_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN:
        return

    if not context.args:
        await update.message.reply_text("Use: /run filename.py")
        return

    filename = context.args[0]
    path = os.path.join(FILES_DIR, filename)

    if not os.path.exists(path):
        await update.message.reply_text("File not found.")
        return

    process = subprocess.Popen(["python", path])
    running_processes[filename] = process.pid

    await update.message.reply_text(f"Running {filename}")


async def running(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not running_processes:
        await update.message.reply_text("No bots running.")
        return

    text = "\n".join(running_processes.keys())
    await update.message.reply_text(text)


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"Files: {len(os.listdir(FILES_DIR))}\nRunning: {len(running_processes)}"
    )


async def contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Owner: @YourUsername")


async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = update.message.text

    if t == "📁 Check Files":
        await check_files(update, context)
    elif t == "🟢 My Running Bots":
        await running(update, context)
    elif t == "📊 My Stats":
        await stats(update, context)
    elif t == "📞 Contact Owner":
        await contact(update, context)


app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("run", run_file))
app.add_handler(MessageHandler(filters.Document.ALL, upload))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, buttons))

app.run_polling()