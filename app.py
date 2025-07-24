import os
import json
from flask import Flask, render_template, request, jsonify
import google.generativeai as genai

# --- Import project modules ---
import config
from tools.get_forecast import get_forecast
from tools.get_candidates import get_candidates
from prompts import TRANSLATOR_SYSTEM_PROMPT

# --- Initialize Flask App ---
app = Flask(__name__)

# --- Configure the Gemini LLM with our tools and persona ---
try:
    genai.configure(api_key=config.GEMINI_API_KEY)

    # Create the model and give it its "job description"
    model = genai.GenerativeModel(
        model_name="gemini-1.5-pro",
        tools=[get_forecast, get_candidates],
        system_instruction=TRANSLATOR_SYSTEM_PROMPT
    )
    print("Gemini Model configured successfully.")
except Exception as e:
    print(f"Error configuring Gemini Model: {e}")
    model = None

# --- Main Application Routes ---
@app.route("/")
def index():
    """Renders the main chat interface page."""
    return render_template("index.html")

@app.route("/ask", methods=["POST"])
def ask():
    """
    This endpoint is the core of the Translator. It handles the user's question,
    orchestrates the LLM and tool calls, and returns the final answer.
    """
    if model is None:
        return jsonify({"error": "Gemini Model is not configured. Check API key."}), 500

    user_question = request.json.get("question")
    if not user_question:
        return jsonify({"error": "No question provided."}), 400

    print(f"--- User question received: '{user_question}' ---")

    try:
        # Start a chat session with automatic function calling enabled
        chat = model.start_chat(enable_automatic_function_calling=True)
        
        # Send the user's message. The model will automatically handle
        # one or more tool calls until it has a final text answer.
        response = chat.send_message(user_question)
        
        final_answer = response.text

        print(f"--- Final answer generated. ---")
        return jsonify({"answer": final_answer})

    except Exception as e:
        print(f"An error occurred during chat generation: {e}")
        return jsonify({"error": f"An unexpected error occurred: {str(e)}"}), 500

if __name__ == "__main__":
    # The host must be 0.0.0.0 to be accessible from outside the Docker container
    app.run(debug=True, host="0.0.0.0", port=5000)