# Dockerfile

# Start with a lightweight, official Python base image
FROM python:3.11-slim

# Set the working directory inside the container
WORKDIR /app

# Copy the requirements file first to leverage Docker's caching
COPY requirements.txt .

# Install all the Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your application's code into the container
COPY . .

# Tell Docker what command to run when the container starts
# The host 0.0.0.0 makes the server accessible from outside the container
CMD ["uvicorn", "ui.app:app", "--host", "0.0.0.0", "--port", "8000"]