FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
RUN pip install --no-cache-dir .
RUN addgroup --system aura && adduser --system --ingroup aura aura
COPY --chown=aura:aura app ./app
USER aura
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
