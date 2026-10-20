# Start the Filament Catalog locally.
# First time only: python -m venv .venv ; .\.venv\Scripts\Activate.ps1 ; pip install -r requirements.txt ; python -m app.seed
uvicorn app.main:app --reload --port 8077
