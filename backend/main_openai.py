from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from openai import OpenAI
import os
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

templates = Jinja2Templates(directory="templates")

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

class Prompt(BaseModel):
    message: str


# Root route
@app.get("/")
def home():

    models = []

    for model in OpenAI.list_models():

        models.append({
            "name": model.name,
            "methods": model.supported_generation_methods
        })

    return {
        "models": models
    }

@app.post("/ask")
def ask_ai(prompt: Prompt):

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a helpful business assistant. Be concise and accurate."},
                {"role": "user", "content": prompt.message}
            ],
            temperature=0.3,
            max_tokens=512
        )

        return {"response": response.choices[0].message.content}
    
    except Exception as e:
        error_str = str(e)
        
        # Check for rate limit / quota exceeded (429)
        if "429" in error_str or "rate_limit" in error_str.lower() or "quota" in error_str.lower():
            return {
                "error": "OpenAI API quota exceeded. Rate limit hit. Please wait and try again.",
                "status_code": 429,
                "details": error_str
            }
        
        return {
            "error": str(e),
            "status_code": 500
        }