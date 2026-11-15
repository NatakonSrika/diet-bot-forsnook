from flask import Flask
import threading
import os
import sqlite3
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, CommandHandler, filters
from google import genai

load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

ai_client = genai.Client(api_key=GEMINI_API_KEY)

# --- Flask Server สำหรับรันบน Render (ป้องการปิดกั้นพอร์ต) ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Smart Diet Bot is running!", 200

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

# เปิดเว็บเซิร์ฟเวอร์แยกอีก Thread หนึ่งทันที
threading.Thread(target=run_web, daemon=True).start()

# --- จัดการฐานข้อมูล SQLite ---
def init_db():
    conn = sqlite3.connect("diet_bot.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            weight REAL,
            height REAL,
            target_calories INTEGER
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            log_type TEXT,
            description TEXT,
            calories INTEGER,
            date TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

# --- คำสั่ง /start และตั้งค่า ---
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = sqlite3.connect("diet_bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()
    conn.close()

    if not user:
        await update.message.reply_text(
            "สวัสดีครับ! ยินดีต้อนรับสู่บอทคุมน้ำหนัก 🥗\n"
            "ก่อนเริ่มใช้งาน รบกวนตั้งค่าเป้าหมายของคุณก่อนครับ โดยพิมพ์:\n"
            "`/set น้ำหนัก ส่วนสูง แคลอรี่ที่ควรได้รับต่อวัน`\n"
            "เช่น: `/set 65 170 2000`",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            "ยินดีต้อนรับกลับครับ! ส่งรูปอาหาร หรือพิมพ์รายการอาหาร/การออกกำลังกายมาได้เลย\n"
            "คำสั่งอื่นๆ:\n"
            "/summary - ดูสรุปแคลอรี่วันนี้"
        )

async def set_user_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args
    if len(args) < 3:
        await update.message.reply_text("พิมพ์ข้อมูลไม่ครบครับ ใช้รูปแบบ: `/set 65 170 2000` (น้ำหนัก ส่วนสูง เป้าหมายแคลอรี่)", parse_mode="Markdown")
        return
    
    try:
        weight = float(args[0])
        height = float(args[1])
        target_cal = int(args[2])
        
        conn = sqlite3.connect("diet_bot.db")
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO users (user_id, weight, height, target_calories) VALUES (?, ?, ?, ?)",
                       (user_id, weight, height, target_cal))
        conn.commit()
        conn.close()
        
        await update.message.reply_text(f"✅ บันทึกข้อมูลเรียบร้อย!\nน้ำหนัก: {weight} กก.\nส่วนสูง: {height} ซม.\nเป้าหมายแคลอรี่: {target_cal} กอลลอรี่/วัน")
    except Exception as e:
        await update.message.reply_text("เกิดข้อผิดพลาด กรุณาตรวจสอบตัวเลขใหม่อีกครั้งครับ")

# --- ฟังก์ชันดูสรุปประจำวัน ---
async def summary_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    today = datetime.now().strftime("%Y-%m-%d")
    
    conn = sqlite3.connect("diet_bot.db")
    cursor = conn.cursor()
    
    cursor.execute("SELECT target_calories FROM users WHERE user_id = ?", (user_id,))
    user_row = cursor.fetchone()
    target_cal = user_row[0] if user_row else 2000 
    
    cursor.execute("SELECT description, calories FROM logs WHERE user_id = ? AND log_type = 'food' AND date = ?", (user_id, today))
    foods = cursor.fetchall()
    
    cursor.execute("SELECT description, calories FROM logs WHERE user_id = ? AND log_type = 'exercise' AND date = ?", (user_id, today))
    exercises = cursor.fetchall()
    conn.close()
    
    total_intake = sum([f[1] for f in foods])
    total_burn = sum([e[1] for e in exercises])
    remaining = target_cal - total_intake + total_burn
    
    msg = f"📊 **สรุปแคลอรี่ประจำวัน ({today})**\n\n"
    msg += f"🎯 เป้าหมาย: {target_cal} kcal\n"
    msg += f"🍽️ กินเข้าไปรวม: {total_intake} kcal\n"
    for f in foods:
        msg += f"  - {f[0]} (+{f[1]})\n"
        
    msg += f"\n🏃 ออกกำลังกายเผาผลาญ: {total_burn} kcal\n"
    for e in exercises:
        msg += f"  - {e[0]} (-{e[1]})\n"
        
    msg += f"\n💡 **เหลือกินได้อีก:** {remaining} kcal\n"
    if remaining < 0:
        msg += "⚠️ วันนี้เกินโควตาแล้วนะ พรุ่งนี้สู้ใหม่ครับ!"
    else:
        msg += "👍 ยังอยู่ในเกณฑ์ที่ดีครับ!"
        
    await update.message.reply_text(msg, parse_mode="Markdown")

# --- ฟังก์ชันจัดการข้อความและรูปภาพผ่าน Gemini ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    today = datetime.now().strftime("%Y-%m-%d")
    
    text_prompt = ""
    image_file_ref = None
    image_path = "temp.jpg"

    if update.message.photo:
        await update.message.reply_text("📸 กำลังส่องรูปและคำนวณแคลอรี่...")
        photo_file = await update.message.photo[-1].get_file()
        await photo_file.download_to_drive(image_path)
        image_file_ref = ai_client.files.upload(file=image_path)
        text_prompt = [
            image_file_ref,
            "วิเคราะห์รูปนี้ว่าเป็นอาหารหรือการออกกำลังกาย ตอบเป็น JSON รูปแบบสั้นที่สุด: "
            '{"type": "food" หรือ "exercise", "name": "ชื่อเมนูหรือกิจกรรม", "calories": ตัวเลขแคลอรี่}'
        ]
    else:
        user_message = update.message.text
        if not user_message:
            return
        await update.message.reply_text("⏳ กำลังประมวลผล...")
        text_prompt = (
            f"ผู้ใช้พิมพ์มาว่า: '{user_message}' "
            "วิเคราะห์ข้อความนี้ว่าเป็นการบอกว่ากินอาหารอะไร หรือออกกำลังกายอะไร ตอบเป็น JSON รูปแบบสั้นที่สุด: "
            '{"type": "food" หรือ "exercise", "name": "ชื่อรายการ", "calories": ตัวเลขแคลอรี่}'
        )

    try:
        response = ai_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=text_prompt,
        )
        
        import json
        import re
        
        res_text = response.text
        match = re.search(r'\{.*\}', res_text, re.DOTALL)
        if match:
            data = json.loads(match.group(0))
            l_type = data.get("type", "food")
            name = data.get("name", "ไม่ระบุ")
            cals = int(data.get("calories", 0))
            
            conn = sqlite3.connect("diet_bot.db")
            cursor = conn.cursor()
            cursor.execute("INSERT INTO logs (user_id, log_type, description, calories, date) VALUES (?, ?, ?, ?, ?)",
                           (user_id, l_type, name, cals, today))
            conn.commit()
            conn.close()
            
            action_str = "กินอาหาร" if l_type == "food" else "ออกกำลังกาย"
            await update.message.reply_text(f"✅ บันทึกสำเร็จ!\n📌 {action_str}: {name}\n🔥 แคลอรี่: {cals} kcal\n\nพิมพ์ /summary เพื่อดูยอดรวมวันนี้ครับ")
        else:
            await update.message.reply_text(res_text)

    except Exception as e:
        print(f"Error: {e}")
        await update.message.reply_text("ขออภัยครับ ระบบประมวลผลไม่สำเร็จ ลองใหม่อีกครั้งนะครับ")
    
    if os.path.exists(image_path):
        os.remove(image_path)

def main():
    app_bot = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    app_bot.add_handler(CommandHandler("start", start_cmd))
    app_bot.add_handler(CommandHandler("set", set_user_cmd))
    app_bot.add_handler(CommandHandler("summary", summary_cmd))
    
    app_bot.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    app_bot.add_handler(MessageHandler(filters.PHOTO, handle_message))

    print("🤖 Smart Diet Bot พร้อมทำงานแล้ว...")
    app_bot.run_polling()

if __name__ == "__main__":
    main()