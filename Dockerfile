# Use official Python slim image
FROM python:3.10-slim

# Set up a new user named "user" with UID 1000
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH

# Set working directory
WORKDIR $HOME/app

# Copy requirements and install dependencies
COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Copy all project files
COPY --chown=user . .

# Hugging Face Spaces expects port 7860
EXPOSE 7860

# Run using Gunicorn on port 7860
CMD ["gunicorn", "-b", "0.0.0.0:7860", "wsgi:app"]
