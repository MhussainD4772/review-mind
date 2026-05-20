FROM python:3.12-slim

# Prevent Python from writing .pyc files and buffering stdout
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

#Set working directory inside the container
WORKDIR /code

#Install system dependencies needed for psycopg2 and other native libs
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*


#Copy requirements first (for Docker layer caching)
COPY requirements.txt .

#Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

#Copy the rest of the application
COPY . .

#Expose FASTapi port
EXPOSE 8000

#Default command - overridden by docker-compose for the worker
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

