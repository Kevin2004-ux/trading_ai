# translator/main.py
import os
import google.generativeai as genai
from dotenv import load_dotenv

import sys
sys.path.append('.')

from tools.get_prediction_dossier import get_prediction_dossier
# CORRECTED IMPORT
from .prompts import SYSTEM_PROMPT

load_dotenv(override=True)
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# Initialize the generative model with its tools and instructions
model = genai.GenerativeModel(
    model_name="gemini-1.5-pro",
    tools=[get_prediction_dossier],
    system_instruction=SYSTEM_PROMPT
)

def ask_translator(question: str) -> str:
    """
    Sends a user's question to the Gemini model and returns its response.
    """
    try:
        chat = model.start_chat(enable_automatic_function_calling=True)
        response = chat.send_message(question)
        return response.text
    except Exception as e:
        print(f"An error occurred with the generative model: {e}")
        return "Sorry, an error occurred while contacting the AI."