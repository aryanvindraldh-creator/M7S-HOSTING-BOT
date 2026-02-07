import os
import subprocess
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

TOKEN = os.getenv("TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

running_bots = {}

keyboard = [
    ["📤 Upload File", "📂 Check Files"],
    ["🟢 My Running Bots", "⛔ Stop All Bots"],
]

markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


# /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ You are not allowed.")
        return

    await update.message.reply_text(
        "🔥 M7S TELI BOT HOSTING READY\n\nSend .py file to run bot.",
        reply_markup=markup,
    )


# file upload
async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    doc = update.message.document
    file = await doc.get_file()

    os.makedirs("files", exist_ok=True)
    path = f"files/{doc.file_name}"
    await file.download_to_drive(path)

    await update.message.reply_text(f"✅ Saved: {doc.file_name}")

    if doc.file_name.endswith(".py"):
        process = subprocess.Popen(["python", path])
        running_bots[doc.file_name] = process
        await update.message.reply_text(f"🚀 Started: {doc.file_name}")


# check files
async def check_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not os.path.exists("files"):
        await update.message.reply_text("No files uploaded.")
        return

    files = os.listdir("files")
    await update.message.reply_text("\n".join(files) if files else "No files.")


# running bots
async def running(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not running_bots:
        await update.message.reply_text("No running bots.")
        return

    await update.message.reply_text("\n".join(running_bots.keys()))


# stop bots
async def stop_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for p in running_bots.values():
        p.kill()

    running_bots.clear()
    await update.message.reply_text("⛔ All bots stopped.")


def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_file))
    app.add_handler(MessageHandler(filters.Regex("📂 Check Files"), check_files))
    app.add_handler(MessageHandler(filters.Regex("🟢 My Running Bots"), running))
    app.add_handler(MessageHandler(filters.Regex("⛔ Stop All Bots"), stop_all))

    print("M7S HOSTING STARTED")
    app.run_polling()


if __name__ == "__main__":
    main()
