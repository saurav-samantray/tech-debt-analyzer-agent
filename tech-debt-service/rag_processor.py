import os
import logging
from pathlib import Path
import config

# Langchain components for RAG
from langchain_community.vectorstores import FAISS
from langchain_openai import OpenAIEmbeddings # If using OpenAI embeddings
from langchain_community.embeddings import HuggingFaceEmbeddings # For Sentence Transformers
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import DirectoryLoader, TextLoader, UnstructuredMarkdownLoader

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class RAGProcessor:
    def __init__(self, norms_dir: str = config.NORMS_DIR, vector_store_path: str = config.VECTOR_STORE_PATH):
        self.norms_dir = norms_dir
        self.vector_store_path = vector_store_path
        self.embeddings = self._get_embedding_model()
        self.vector_store = self._load_or_create_vector_store()

    def _get_embedding_model(self):
        """Initializes the embedding model."""
        # Example: Using Sentence Transformers (works locally)
        logging.info(f"Initializing embedding model: {config.EMBEDDING_MODEL_NAME}")
        # Specify device='cuda' if GPU is available and configured
        model_kwargs = {'device': 'cpu'}
        encode_kwargs = {'normalize_embeddings': False}
        return HuggingFaceEmbeddings(
            model_name=config.EMBEDDING_MODEL_NAME,
            model_kwargs=model_kwargs,
            encode_kwargs=encode_kwargs
        )
        # --- OR ---
        # Example: Using OpenAI Embeddings (requires API key)
        # if config.OPENAI_API_KEY:
        #     logging.info("Initializing OpenAI embedding model.")
        #     return OpenAIEmbeddings(api_key=config.OPENAI_API_KEY)
        # else:
        #     raise ValueError("OpenAI API Key needed for OpenAI embeddings, but not found.")

    def _load_norms(self) -> list:
        """Loads documents from the norms directory."""
        logging.info(f"Loading norms from directory: {self.norms_dir}")
        # Use DirectoryLoader with specific loaders for file types
        # This requires 'unstructured' and potentially 'pypandoc'/'pandoc'
        loaders = {
            ".txt": TextLoader,
            ".md": UnstructuredMarkdownLoader, # Requires 'unstructured' library
        }
        docs = []
        if not os.path.exists(self.norms_dir):
             logging.warning(f"Norms directory {self.norms_dir} not found. RAG will have no context.")
             return []

        for ext, loader_cls in loaders.items():
            try:
                loader = DirectoryLoader(
                    self.norms_dir,
                    glob=f"**/*{ext}",
                    loader_cls=loader_cls,
                    show_progress=True,
                    use_multithreading=True, # Can speed up loading
                    silent_errors=True # Log errors but continue
                )
                loaded_docs = loader.load()
                if loaded_docs:
                    logging.info(f"Loaded {len(loaded_docs)} documents with extension {ext}")
                    docs.extend(loaded_docs)
                else:
                    logging.info(f"No documents found with extension {ext}")
            except Exception as e:
                logging.error(f"Error loading files with extension {ext}: {e}")

        logging.info(f"Total documents loaded: {len(docs)}")
        return docs

    def _create_vector_store(self):
        """Creates and saves a new vector store."""
        docs = self._load_norms()
        if not docs:
            logging.warning("No norm documents found or loaded. Cannot create vector store.")
            return None

        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=config.CHUNK_SIZE,
            chunk_overlap=config.CHUNK_OVERLAP
        )
        splits = text_splitter.split_documents(docs)
        logging.info(f"Split {len(docs)} documents into {len(splits)} chunks.")

        if not splits:
             logging.warning("No text chunks generated after splitting. Cannot create vector store.")
             return None

        logging.info(f"Creating FAISS vector store at {self.vector_store_path}...")
        try:
            db = FAISS.from_documents(splits, self.embeddings)
            db.save_local(self.vector_store_path)
            logging.info("Vector store created and saved successfully.")
            return db
        except Exception as e:
            logging.error(f"Failed to create or save FAISS vector store: {e}")
            return None


    def _load_or_create_vector_store(self):
        """Loads an existing vector store or creates a new one."""
        if os.path.exists(self.vector_store_path) and os.listdir(self.vector_store_path):
            logging.info(f"Loading existing vector store from {self.vector_store_path}")
            try:
                # Allow dangerous deserialization if using custom code in embeddings/docs
                # Be cautious if the vector store comes from an untrusted source.
                return FAISS.load_local(
                    self.vector_store_path,
                    self.embeddings,
                    allow_dangerous_deserialization=True # Needed for FAISS with HuggingFaceEmbeddings
                )
            except Exception as e:
                logging.error(f"Error loading vector store: {e}. Attempting to recreate.")
                # Fallback to creating a new one if loading fails
                return self._create_vector_store()
        else:
            logging.info("No existing vector store found. Creating a new one.")
            return self._create_vector_store()

    def retrieve_relevant_norms(self, query_text: str, k: int = config.RAG_TOP_K) -> list[str]:
        """Retrieves relevant norm chunks based on the query text."""
        if self.vector_store is None:
            logging.warning("Vector store not available. Cannot retrieve norms.")
            return []
        try:
            retriever = self.vector_store.as_retriever(search_kwargs={"k": k})
            relevant_docs = retriever.invoke(query_text) # Use invoke for newer Langchain versions
            logging.debug(f"Retrieved {len(relevant_docs)} norms for query.")
            # Return page content of retrieved documents
            return [doc.page_content for doc in relevant_docs]
        except Exception as e:
            logging.error(f"Error during RAG retrieval: {e}")
            return []

    def rebuild_index(self):
        """Forces reloading norms and rebuilding the vector store index."""
        logging.info("Rebuilding RAG index...")
        self.vector_store = self._create_vector_store()
        logging.info("RAG index rebuild complete.")

# Example usage (optional, for testing)
if __name__ == "__main__":
    # Create dummy norm files if they don't exist
    if not os.path.exists(config.NORMS_DIR) or not os.listdir(config.NORMS_DIR):
        os.makedirs(config.NORMS_DIR, exist_ok=True)
        with open(os.path.join(config.NORMS_DIR, "example_norm_1.md"), "w") as f:
            f.write("# Coding Standards\n\nAll functions should have docstrings.\nVariables should be snake_case.")
        with open(os.path.join(config.NORMS_DIR, "example_norm_2.txt"), "w") as f:
            f.write("Performance Guideline: Avoid nested loops if possible. Consider using vectorized operations.")
        print("Created dummy norm files.")

    rag_processor = RAGProcessor()
    rag_processor.rebuild_index() # Build it initially
    print("RAG Processor Initialized.")
    query = "def my_function(x): # What about docstrings?"
    norms = rag_processor.retrieve_relevant_norms(query)
    print(f"\nRelevant norms for query '{query}':")
    for norm in norms:
        print(f"- {norm[:100]}...") # Print snippet
