# Use a Python base image
FROM python:3.11-slim

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# NO LONGER SET FLASK_ENV HERE. Let docker-compose handle it.
# ENV FLASK_APP=run.py # You can keep this or set it in docker-compose as well

# Expose the port your Flask app runs on
EXPOSE 5000 


# Command to run the application using Gunicorn
CMD ["gunicorn", "--config", "gunicorn-cfg.py", "run:app"]