FROM python:3.10-slim AS base

WORKDIR /app

# Copy backend code
COPY backend/ ./backend
COPY backend/templates ./templates 

# Copy contracts
COPY contracts/ ./contracts

# Install backend
RUN pip install --upgrade pip && pip install -e ./backend

EXPOSE 4284

FROM base AS escrow-bridge-listener
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "4284", "--log-level", "debug"]
