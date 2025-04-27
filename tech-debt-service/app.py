
# Flask application for Tech Debt Analyzer API
# This application provides endpoints to start scans, check their status, and rebuild the RAG index.
import os
import logging
from flask import Flask, request, jsonify
from flask_cors import CORS
import threading
import time # Needed for sleep if using polling simulation

import config
from agent import run_scan
from rag_processor import RAGProcessor # Import for rebuild endpoint
import utils # For job ID generation

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = config.FLASK_SECRET_KEY

# 2. Initialize CORS
# Allow requests from all origins by default.
# For production, you might want to restrict origins:
# CORS(app, resources={r"/*": {"origins": "http://localhost:3000"}}) # Example for React default port
CORS(app, resources={r"/*": {"origins": "http://localhost:3000"}})

# In-memory storage for job status and results
# WARNING: This is not persistent and not suitable for production.
# Use Redis, a database, or a proper task queue (Celery) for production.
jobs = {} # Dictionary to store job_id -> job_data

# Lock for thread-safe access to the 'jobs' dictionary
jobs_lock = threading.Lock()

# --- Helper Function for Background Task ---
def run_scan_background(job_id, repo_url, llm_type):
    """Target function for the background thread."""
    global jobs
    logger.info(f"Starting background scan for job_id: {job_id}")
    scan_results = {}
    try:
        # Update status to RUNNING immediately after thread starts
        with jobs_lock:
            if job_id in jobs:
                jobs[job_id]["status"] = "RUNNING"
                jobs[job_id]["start_time"] = time.time() # Record start time
            else:
                 logger.error(f"Job {job_id} not found in jobs dict at start of background task.")
                 return # Should not happen if called correctly

        # Execute the main scan logic
        scan_results = run_scan(job_id, repo_url, llm_type)

        # Update the jobs dictionary with the final results
        with jobs_lock:
            if job_id in jobs:
                # Merge results, preserving initial info if needed
                jobs[job_id].update(scan_results)
                jobs[job_id]["end_time"] = time.time() # Record end time
            else:
                # This case might occur if the job was somehow removed
                logger.warning(f"Job {job_id} finished but was not found in jobs dict. Storing results anyway.")
                jobs[job_id] = scan_results # Store fresh results

        logger.info(f"Background scan finished for job_id: {job_id}. Final Status: {scan_results.get('status')}")

    except Exception as e:
        logger.exception(f"Critical error in background thread for job {job_id}: {e}")
        # Update job status to FAILED on unexpected thread error
        with jobs_lock:
            if job_id in jobs:
                jobs[job_id]["status"] = "FAILED"
                jobs[job_id]["error"] = f"Background task failed unexpectedly: {str(e)}"
                jobs[job_id]["end_time"] = time.time()
            else:
                 # Store error info even if job entry was lost
                 jobs[job_id] = {
                     "job_id": job_id,
                     "status": "FAILED",
                     "error": f"Background task failed unexpectedly after job entry lost: {str(e)}",
                     "findings": [],
                     "end_time": time.time()
                 }

# --- API Endpoints ---

@app.route('/scan', methods=['POST'])
def start_scan_endpoint():
    """
    Starts a new tech debt scan.
    Requires JSON body: {"repo_url": "...", "llm_type": "openai|ollama"}
    """
    global jobs
    data = request.get_json()

    if not data:
        logger.warning("Received empty request body for /scan")
        return jsonify({"error": "Request body must be JSON"}), 400

    repo_url = data.get('repo_url')
    llm_type = data.get('llm_type', '').lower() # Default to empty string, then lower

    # --- Input Validation ---
    errors = {}
    if not repo_url:
        errors['repo_url'] = "Missing 'repo_url' field."
    # Add more robust URL validation if needed
    elif not isinstance(repo_url, str) or not repo_url.startswith(('http://', 'https://', 'git@')):
         errors['repo_url'] = "Invalid 'repo_url' format. Must be a valid Git URL."

    if not llm_type:
         errors['llm_type'] = "Missing 'llm_type' field."
    elif llm_type not in ['openai', 'ollama']:
        errors['llm_type'] = "Invalid 'llm_type'. Must be 'openai' or 'ollama'."
    else:
        # Check configuration based on selected type
        if llm_type == 'openai' and not config.OPENAI_API_KEY:
            errors['config_openai'] = "OpenAI API key (OPENAI_API_KEY) is not configured in the environment."
        if llm_type == 'ollama' and not config.OLLAMA_BASE_URL:
            errors['config_ollama'] = "Ollama base URL (OLLAMA_BASE_URL) is not configured in the environment."
        # Add check for Ollama model availability if desired (requires ollama client here)

    if errors:
        logger.warning(f"Scan request validation failed: {errors}")
        return jsonify({"error": "Invalid request parameters", "details": errors}), 400

    # --- Job Creation ---
    job_id = utils.generate_job_id()
    job_data = {
        "job_id": job_id,
        "status": "PENDING", # Initial status before thread starts
        "repo_url": repo_url,
        "llm_type": llm_type,
        "submitted_at": time.time(),
        "findings": [], # Initialize findings list
        "error": None
    }

    with jobs_lock:
        jobs[job_id] = job_data

    # --- Start Background Task ---
    try:
        thread = threading.Thread(target=run_scan_background, args=(job_id, repo_url, llm_type), daemon=True)
        # daemon=True allows the main Flask app to exit even if scan threads are running.
        # Set to False if you need scans to complete before the app can shut down gracefully.
        thread.start()
        logger.info(f"Scan initiated for {repo_url} using {llm_type}. Job ID: {job_id}")
        # Return the initial job data with the PENDING status
        return jsonify(job_data), 202 # HTTP 202 Accepted: Request accepted, processing started

    except Exception as e:
         logger.exception(f"Failed to start background thread for job {job_id}: {e}")
         # Clean up job entry if thread failed to start
         with jobs_lock:
             if job_id in jobs:
                 del jobs[job_id]
         return jsonify({"error": "Failed to initiate scan process."}), 500


@app.route('/status/<job_id>', methods=['GET'])
def get_status_endpoint(job_id):
    """Checks the status and results of a scan job."""
    global jobs

    with jobs_lock:
        job_info = jobs.get(job_id) # Get a copy or access safely

    if not job_info:
        logger.warning(f"Status request for unknown job_id: {job_id}")
        return jsonify({"error": "Job ID not found"}), 404

    # Return the current state of the job (make a copy to avoid race conditions if needed)
    # Since we're using a lock, accessing job_info directly after retrieval is safe here.
    return jsonify(job_info)

@app.route('/rag/rebuild', methods=['POST'])
def rebuild_rag_index_endpoint():
    """
    Triggers a rebuild of the RAG vector store index.
    NOTE: This runs synchronously and might block the server for a while.
    Consider making this asynchronous for production.
    """
    logger.info("Received request to rebuild RAG index.")
    # Potentially add authentication/authorization here
    try:
        # Initialize the processor which handles loading/creating the store
        rag_processor = RAGProcessor()
        # Call the explicit rebuild method
        rag_processor.rebuild_index()
        logger.info("RAG index rebuild completed successfully.")
        return jsonify({"message": "RAG index rebuild successful."}), 200
    except Exception as e:
        logger.exception("Error during RAG index rebuild:")
        return jsonify({"error": f"Failed to rebuild RAG index: {str(e)}"}), 500

@app.route('/', methods=['GET'])
def index():
    """Simple index route to confirm the server is running."""
    logger.debug("Index route accessed.")
    return jsonify({
        "message": "Tech Debt Analyzer API is running.",
        "version": "1.0.0", # Example version
        "endpoints": {
            "start_scan": "POST /scan",
            "check_status": "GET /status/<job_id>",
            "rebuild_rag": "POST /rag/rebuild"
        }
    })

# --- Utility Function for Initial Setup ---
def ensure_initial_setup():
    """Checks for norms dir and optionally creates dummy files and index."""
    logger.info("Performing initial setup check...")
    norms_exist = os.path.exists(config.NORMS_DIR) and os.listdir(config.NORMS_DIR)

    if not norms_exist:
        logger.warning(f"Norms directory '{config.NORMS_DIR}' is empty or does not exist.")
        try:
            os.makedirs(config.NORMS_DIR, exist_ok=True)
            dummy_norm_path = os.path.join(config.NORMS_DIR, "placeholder_norm.txt")
            if not os.path.exists(dummy_norm_path):
                 with open(dummy_norm_path, "w") as f:
                    f.write("This is a placeholder norm file. Replace with your actual organizational norms.\n")
                 logger.info(f"Created placeholder norm file: {dummy_norm_path}")
            else:
                 logger.info("Placeholder norm file already exists.")
            # Attempt to build index even with placeholder
            logger.info("Attempting to build initial RAG index with placeholder norm...")
            rag_proc = RAGProcessor()
            rag_proc.rebuild_index() # This will create an index based on the placeholder
        except Exception as e:
            logger.error(f"Failed during initial setup (creating norms/building index): {e}")
    else:
        logger.info(f"Norms directory '{config.NORMS_DIR}' found. Assuming RAG index exists or will be loaded/created by RAGProcessor on demand.")
        # Optionally trigger a check/build here too if you want to ensure it's always fresh on startup
        # try:
        #     logger.info("Verifying/Loading RAG index on startup...")
        #     RAGProcessor() # Instantiating it triggers load/create
        # except Exception as e:
        #     logger.error(f"Failed to load/create RAG index on startup: {e}")


# --- Main Execution ---
if __name__ == '__main__':
    ensure_initial_setup()
    # Run Flask app
    # Use host='0.0.0.0' to make it accessible on the network
    # Use debug=False for production/stable runs
    logger.info("Starting Flask application server...")
    app.run(host='0.0.0.0', port=5001, debug=False)
