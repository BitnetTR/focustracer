# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set environment variables to prevent Python from writing pyc files and buffering stdout
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set the working directory in the container
WORKDIR /app

# Install system dependencies (needed for some optional python packages)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy the project files into the container
COPY . /app/

# Install FocusTracer and its dependencies via pip
RUN pip install --no-cache-dir -e .

# Expose the port that the FocusTracer GUI runs on
EXPOSE 8765

# Command to run the application binding to 0.0.0.0 so it is accessible outside the container
CMD ["focustracer", "gui", "--host", "0.0.0.0", "--port", "8765", "--no-browser"]
