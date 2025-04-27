import os
from dotenv import load_dotenv

load_dotenv()

# --- General ---
FLASK_SECRET_KEY = os.getenv('FLASK_SECRET_KEY', 'default-secret-key')
REPO_CLONE_DIR = os.getenv('REPO_CLONE_DIR', './cloned_repos')
NORMS_DIR = os.getenv('NORMS_DIR', './norms')
ALLOWED_EXTENSIONS = os.getenv('ALLOWED_EXTENSIONS', '.py').split(',')

# --- RAG ---
EMBEDDING_MODEL_NAME = os.getenv('EMBEDDING_MODEL_NAME', 'all-MiniLM-L6-v2')
VECTOR_STORE_PATH = os.getenv('VECTOR_STORE_PATH', './vector_store_faiss')
CHUNK_SIZE = int(os.getenv('CHUNK_SIZE', 1000))
CHUNK_OVERLAP = int(os.getenv('CHUNK_OVERLAP', 100))
RAG_TOP_K = int(os.getenv('RAG_TOP_K', 3))

# --- LLM ---
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
OPENAI_MODEL_NAME = os.getenv('OPENAI_MODEL_NAME', 'gpt-4o-mini')
OLLAMA_BASE_URL = os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434')
OLLAMA_MODEL_NAME = os.getenv('OLLAMA_MODEL_NAME', 'llama3') # Ensure this model is pulled in Ollama

# --- Agent ---
TECH_DEBT_CATEGORIES = os.getenv('TECH_DEBT_CATEGORIES', 'Unknown')

# --- Derived ---
os.makedirs(REPO_CLONE_DIR, exist_ok=True)
os.makedirs(NORMS_DIR, exist_ok=True)
os.makedirs(os.path.dirname(VECTOR_STORE_PATH), exist_ok=True)

# --- Validation ---
if not OPENAI_API_KEY and not OLLAMA_BASE_URL:
    print("Warning: Neither OpenAI API Key nor Ollama Base URL is configured.")

