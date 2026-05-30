from fastapi import FastAPI
from pydantic import BaseModel
import google.generativeai as genai
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Create FastAPI app
app = FastAPI()

# Configure Gemini API
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# Load working model
model = genai.GenerativeModel("models/gemini-2.0-flash-lite")

# Request schema
class Prompt(BaseModel):
    message: str

# Root route
@app.get("/")
def home():
    return {
        "message": "Gemini AI server running"
    }

# AI route
@app.post("/ask")
def ask_ai(prompt: Prompt):

    try:
        # Gemini system context is set via SafetySettings, prompt is concise
        system_instruction = "You are BIZASSIST AI for Indian retail business. Be concise. Answer only with provided data."
        
        model = genai.GenerativeModel(
            "models/gemini-2.0-flash-lite",
            system_instruction=system_instruction
        )

        response = model.generate_content(prompt.message)

        return {
            "response": response.text
        }

    except Exception as e:
        error_str = str(e)
        
        # Check for rate limit / quota exceeded (429)
        if "429" in error_str or "rate_limit" in error_str.lower() or "quota" in error_str.lower():
            return {
                "error": "Gemini API quota exceeded. Rate limit hit. Please wait and try again.",
                "status_code": 429,
                "details": error_str
            }
        
        return {
            "error": str(e),
            "status_code": 500
        }