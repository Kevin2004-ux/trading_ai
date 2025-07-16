# app.py

import os
import json
from flask import Flask, render_template, request, jsonify, abort
import google.generativeai as genai
import pinecone

# --- Initialization with Hardcoded Example Keys ---
app = Flask(__name__)

# Configure Gemini
genai.configure(api_key="AIzaSyC22qRusjJj8hQpxmBYuHct7P9BuKacZM8")
chat_model = genai.GenerativeModel('gemini-1.5-flash')

# Initialize Pinecone
pc = pinecone.Pinecone(api_key="pcsk_4BBWsX_Q2VD8YiMc9SpKuNjijQmXeoYVaMUBPMP2WvWWSvStmsiTi5AdLDtHw5y8ie5jKq")
INDEX_NAME = "trade-signal-library"
index = pc.Index(INDEX_NAME)
# ---------------------------------------------

# Load the final, analyzed patterns for the library page
try:
    with open("final_analysis.jsonl") as f:
        PATTERNS = [json.loads(line) for line in f]
except FileNotFoundError:
    print("Warning: final_analysis.jsonl not found. Run the full data pipeline first.")
    PATTERNS = []

# --- Routes ---
@app.route("/")
@app.route("/library")
def library():
    """Renders the main pattern library page."""
    return render_template("library.html", patterns=PATTERNS, active='library')

@app.route("/alerts")
def alerts():
    """Renders the live alerts page (placeholder)."""
    return render_template("alerts.html", alerts=[], active='alerts')

@app.route("/pattern/<pattern_id>")
def pattern_detail(pattern_id):
    """Renders the detail page for a specific analyzed pattern."""
    pattern = next((p for p in PATTERNS if p['pattern_id'] == pattern_id), None)
    if not pattern:
        abort(404)
    return render_template("pattern_detail.html", pattern=pattern)

@app.route("/ask", methods=["POST"])
def ask():
    """Handles a user's question about a specific pattern."""
    data = request.json
    question = data.get("question", "").strip()
    pattern_id = data.get("pattern_id", "").strip()
    if not question or not pattern_id:
        return jsonify({"error": "Missing question or pattern_id"}), 400

    # 1. Fetch the specific aggregated dossier from Pinecone to use as context
    try:
        fetch_response = index.fetch(ids=[pattern_id], namespace='vetted-patterns')
        if not fetch_response['vectors'] or pattern_id not in fetch_response['vectors']:
             return jsonify({"error": "Could not find that pattern in the smart library."}), 404
        context = fetch_response['vectors'][pattern_id]['metadata']['dossier']
    except Exception as e:
        return jsonify({"error": f"Error fetching from Pinecone: {e}"}), 500

    # 2. Build a prompt and ask Gemini for an expert explanation
    prompt = (
      f"You are an expert trading analyst. A user is asking a question about a specific trading pattern you have analyzed. "
      f"Based ONLY on the following data dossier for that pattern, provide a clear and concise answer.\n\n"
      f"--- Data Dossier ---\n{context}\n\n"
      f"--- User's Question ---\n{question}\n\n"
      f"ANSWER:"
    )
    
    try:
        response = chat_model.generate_content(prompt)
        return jsonify(answer=response.text)
    except Exception as e:
        return jsonify(error=f"Error generating response: {e}"), 500

if __name__ == "__main__":
    app.run(debug=True)
