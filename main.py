import os
import subprocess
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

TOKEN = os.getenv("TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

RUNNING_BOTS = {}

keyboard = [
    ["📤 Upload File", "📂 Check Files"],
    ["🟢 My Running Bots", "⛔ Stop Bot"],
]

markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


# /start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ You are not allowed.")
        return

    await update.message.reply_text(
        "🔥 *M7S TELI BOT HOSTING*\n\nSend a Python/JS/ZIP file to run bot.",
        parse_mode="Markdown",
        reply_markup=markup,
    )


# Handle file upload
async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    doc = update.message.document
    file = await doc.get_file()

    os.makedirs("files", exist_ok=True)
    path = f"files/{doc.file_name}"
    await file.download_to_drive(path)

    await update.message.reply_text(f"✅ File saved:\n`{doc.file_name}`", parse_mode="Markdown")

    # auto run .py files
    if doc.file_name.endswith(".py"):
        process = subprocess.Popen(["python", path])
        RUNNING_BOTS[doc.file_name] = process
        await update.message.reply_text(f"🚀 Bot started:\n`{doc.file_name}`", parse_mode="Markdown")


# Show files
async def check_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    if not os.path.exists("files"):
        await update.message.reply_text("📂 No files uploaded.")
        return

    files = os.listdir("files")
    if not files:
        await update.message.reply_text("📂 No files uploaded.")
        return

    await update.message.reply_text("📁 Files:\n" + "\n".join(files))


# Show running bots
async def running(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    if not RUNNING_BOTS:
        await update.message.reply_text("🔴 No bots running.")
        return

    await update.message.reply_text("🟢 Running:\n" + "\n".join(RUNNING_BOTS.keys()))


# Stop all bots
async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    for p in RUNNING_BOTS.values():
        p.kill()

    RUNNING_BOTS.clear()
    await update.message.reply_text("⛔ All bots stopped.")


# Main
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_file))
    app.add_handler(MessageHandler(filters.Regex("📂 Check Files"), check_files))
    app.add_handler(MessageHandler(filters.Regex("🟢 My Running Bots"), running))
    app.add_handler(MessageHandler(filters.Regex("⛔ Stop Bot"), stop))

    print("🔥 M7S TELI BOT HOSTING STARTED")
    app.run_polling()


if __name__ == "__main__":
    main()
