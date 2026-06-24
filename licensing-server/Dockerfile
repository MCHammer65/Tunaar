# Tunaar licensing webhook — owner-side service (NOT shipped to customers).
FROM python:3.12-slim
WORKDIR /app

COPY licensing-server/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# The webhook reuses the signer in the tunaar package.
COPY tunaar ./tunaar
COPY licensing-server ./licensing-server

EXPOSE 8080
CMD ["python", "licensing-server/webhook.py"]
