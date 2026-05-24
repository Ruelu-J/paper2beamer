FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    texlive-latex-recommended \
    texlive-latex-extra \
    texlive-fonts-recommended \
    latexmk \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY paper2beamer/ ./paper2beamer/
COPY templates/ ./templates/
COPY pyproject.toml .
RUN pip install -e .

RUN mkdir -p /app/data/cache /app/data/outputs /app/data/templates /app/data/uploads

EXPOSE 8000

CMD ["paper2beamer", "serve"]
