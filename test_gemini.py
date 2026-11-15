import os
from dotenv import load_dotenv
from google import genai

load_dotenv()  # อ่านค่าจากไฟล์ .env

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

response = client.models.generate_content(
    model="gemini-3.8-flash",
    contents="ข้าวกะเพราหมูสับไข่ดาว 1 จาน ประมาณกี่แคลอรี่ ตอบสั้นๆ",
)

print(response.text)