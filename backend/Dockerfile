FROM python:3.12-slim
WORKDIR /app
ENV PYTHONPATH=/app PYTHONUNBUFFERED=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY thz ./thz
RUN printf '#!/bin/sh\nexec python -m thz "$@"\n' > /usr/local/bin/thz && chmod +x /usr/local/bin/thz
CMD ["uvicorn", "thz.api:app", "--host", "0.0.0.0", "--port", "8000"]
