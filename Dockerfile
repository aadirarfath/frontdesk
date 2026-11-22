FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN useradd --create-home frontdesk
COPY app.py business_calendar.py schema.sql ./
COPY frontdesk.html frontdesk.css frontdesk.js ./
USER frontdesk
EXPOSE 8000
CMD ["python", "app.py"]
