# ui/app.py

from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel
import sys
sys.path.append('.')

from tools.get_prediction_dossier import get_prediction_dossier
from translator.main import ask_translator

app = FastAPI(title="Trading AI API")

# Define the request body for the /ask endpoint
class AskRequest(BaseModel):
    question: str

# --- API Endpoints ---
@app.get("/")
async def read_index():
    return FileResponse("ui/templates/index.html")

@app.get("/predict/{ticker}")
async def predict_stock(ticker: str):
    """API endpoint to get the raw prediction dossier."""
    return get_prediction_dossier(ticker)

@app.post("/ask")
async def ask(request: AskRequest):
    """
    The main endpoint for the chat interface. It takes a natural language
    question and returns a synthesized answer from the Translator AI.
    """
    print(f"Received question: {request.question}")
    answer = ask_translator(request.question)
    return {"answer": answer}