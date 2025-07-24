# retrain/generate_feature_hypotheses.py

import os
import google.generativeai as genai
import config
import json

def generate_hypotheses(base_features, symbolic_formula):
    """Asks the LLM to brainstorm new features based on existing ones."""
    print("Asking Gemini to generate feature hypotheses...")
    genai.configure(api_key=config.GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash')

    prompt = f"""
You are an expert quantitative financial analyst. Your task is to brainstorm new, advanced features for a stock return prediction model.

The model currently uses these base features, accessible in a numpy array `z`:
{json.dumps(base_features, indent=2)}

The model's core logic is captured by this simple symbolic formula:
{symbolic_formula}

Based on your understanding of financial markets, propose up to 15 new interaction features. These should represent plausible economic relationships (e.g., 'RSI is more potent when VIX is high').

Return ONLY a valid JSON object (no markdown formatting) where each key is the new feature name (e.g., "RSI_x_VIX") and the value is a single line of Python code to calculate it from the numpy array `z`.

Example format:
{{
  "ATR_x_Regime": "z[5] * z[4]",
  "Vol_x_Slope": "z[1] * z[0]"
}}
"""

    try:
        response = model.generate_content(prompt)
        # Clean up potential markdown formatting from the LLM response
        cleaned_response = response.text.replace("```json", "").replace("```", "").strip()
        hypotheses = json.loads(cleaned_response)
        print(f"Successfully generated {len(hypotheses)} new feature hypotheses.")
        return hypotheses
    except Exception as e:
        print(f"An error occurred with the Gemini API or JSON parsing: {e}")
        return {}