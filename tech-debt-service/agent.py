import os
import logging
import time
import json
import re # Import re for parsing

import config
import utils
from rag_processor import RAGProcessor
# Import the parser function correctly
from llm_interface import generate_completion, parse_llm_response_to_json

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Prompt Engineering ---

def create_system_prompt():
    """Creates the system prompt for the LLM."""
    # Ensure TECH_DEBT_CATEGORIES is properly fetched from config
    categories = config.TECH_DEBT_CATEGORIES
    return f"""You are an AI assistant specialized in analyzing source code to identify technical debt.
Your goal is to find potential issues related to the following categories: {categories}.

You will be given a code snippet and potentially relevant excerpts from the organization's coding standards and architectural norms.

Analyze the provided code snippet carefully.
Consider the provided organizational norms. If the code violates any specific norm, mention it.
Identify specific instances of technical debt within the code.
For each instance found, provide:
1.  `line_number`: The approximate starting line number of the issue in the snippet.
2.  `category`: One of the predefined categories: {categories}.
3.  `description`: A concise explanation of the technical debt and why it's an issue.
4.  `severity`: Estimate the severity (e.g., Low, Medium, High).
5.  `norm_violated`: (Optional) The specific organizational norm violated, if applicable.

Format your response STRICTLY as a JSON list of objects. Each object represents one piece of identified technical debt.
Example:
[
  {{
    "line_number": 15,
    "category": "Readability",
    "description": "Variable name 'x' is too generic. Consider a more descriptive name.",
    "severity": "Low",
    "norm_violated": "Variables should be descriptive (Section 3.2)"
  }},
  {{
    "line_number": 28,
    "category": "Maintainability",
    "description": "Function exceeds 100 lines, making it hard to understand and maintain.",
    "severity": "Medium",
    "norm_violated": null
  }}
]

If no technical debt is found in the snippet, return an empty JSON list: [].
Do NOT include any explanations, introductory text, or markdown formatting like ```json before or after the JSON list itself. Just output the raw JSON list.
"""

def create_user_prompt(code_snippet: str, relevant_norms: list[str]) -> str:
    """Creates the user prompt for the LLM."""
    norm_section = "No specific organizational norms provided for context."
    if relevant_norms:
        norm_section = "Consider these relevant organizational norms/guidelines:\n"
        for i, norm in enumerate(relevant_norms):
            # Ensure norms are clearly separated and formatted
            norm_section += f"\n--- Norm {i+1} Start ---\n{norm}\n--- Norm {i+1} End ---\n"
        norm_section += "\n--- End of Norms ---"

    # Ensure the code snippet is clearly demarcated
    return f"""{norm_section}
Analyze the following code snippet for technical debt based on the categories and format instructions provided in the system prompt:

```code
{code_snippet}
Remember to respond ONLY with the raw JSON list of findings, nothing else. """

def analyze_code_file(repo_base_path: str, relative_file_path: str, rag_processor: RAGProcessor, llm_type: str) -> list:
    """Analyzes a single code file for technical debt."""
    logging.info(f"Analyzing file: {relative_file_path}")
    code_content = utils.read_file_content(repo_base_path, relative_file_path)
    if not code_content:
        logging.warning(f"Skipping empty or unreadable file: {relative_file_path}")
        return []

    # --- RAG Step ---
    # Use file content (or potentially chunks/summaries for large files) to find relevant norms
    # TODO: Add check for file size and implement chunking if needed
    relevant_norms = rag_processor.retrieve_relevant_norms(code_content)
    logging.debug(f"Retrieved {len(relevant_norms)} norms for {relative_file_path}")

    # --- LLM Step ---
    # TODO: Implement chunking for files exceeding context window limits.
    system_prompt = create_system_prompt()
    user_prompt = create_user_prompt(code_content, relevant_norms)

    llm_response_text = generate_completion(llm_type, user_prompt, system_prompt)

    if not llm_response_text:
        logging.error(f"Failed to get LLM response for file: {relative_file_path}")
        return [] # Return empty list for this file on failure

    # --- Parsing Step ---
    # Use the dedicated parser function from llm_interface
    parsed_findings = parse_llm_response_to_json(llm_response_text)

    if parsed_findings is None:
        logging.error(f"Failed to parse LLM response into JSON for file: {relative_file_path}. Response snippet: {llm_response_text[:200]}...")
        return [] # Return empty list if parsing fails

    # Ensure the result is a list, even if the LLM mistakenly returned a single object
    if isinstance(parsed_findings, dict):
        logging.warning(f"LLM response for {relative_file_path} was a single JSON object, expected list. Wrapping it in a list.")
        parsed_findings = [parsed_findings]
    elif not isinstance(parsed_findings, list):
        logging.error(f"Parsed LLM response for {relative_file_path} is not a list or dict. Type: {type(parsed_findings)}. Response snippet: {llm_response_text[:200]}...")
        return [] # Return empty list if the structure is unexpected

    # Add file context and validate each finding
    file_results = []
    for finding in parsed_findings:
        if isinstance(finding, dict):
            # Basic validation of expected keys (adjust as needed)
            required_keys = ["line_number", "category", "description", "severity"]
            if all(key in finding for key in required_keys):
                finding['file'] = relative_file_path # Add file path context
                # Ensure category is one of the allowed ones (optional strict check)
                allowed_categories = [cat.strip() for cat in config.TECH_DEBT_CATEGORIES.split(',')]
                if finding.get('category') not in allowed_categories:
                    logging.warning(f"Finding in {relative_file_path} has invalid category '{finding.get('category')}'. Allowed: {allowed_categories}. Keeping it for now.")
                    # Optionally: finding['category'] = 'Unknown' or skip the finding
                file_results.append(finding)
            else:
                logging.warning(f"Skipping malformed finding in {relative_file_path} (missing keys): {finding}")
        else:
            logging.warning(f"Skipping non-dict item in parsed list for {relative_file_path}: {finding}")

    logging.info(f"Found {len(file_results)} potential tech debt items in {relative_file_path}")
    return file_results

def run_scan(job_id: str, repo_url: str, llm_type: str) -> dict:
    """The main agentic workflow: clone, setup RAG, scan files, aggregate results"""
    start_time = time.time()
    # Initialize results structure clearly 
    results = { "job_id": job_id, "repo_url": repo_url, "llm_type": llm_type, "status": "INITIALIZING", "findings": [], "error": None, "files_scanned": 0, "total_files": 0, "duration_seconds": 0.0 }
    repo_path = None

    try:
        results["status"] = "CLONING"
        logging.info(f"[{job_id}] Starting scan for repo: {repo_url}")
        # 1. Clone Repo
        repo_path = utils.clone_repo(repo_url, job_id)
        if not repo_path:
            raise ValueError(f"Failed to clone repository: {repo_url}")
        logging.info(f"[{job_id}] Repository cloned to: {repo_path}")

        results["status"] = "INITIALIZING_RAG"
        # 2. Initialize RAG
        # Ensure index is up-to-date if norms change frequently, otherwise loading is fine
        rag_processor = RAGProcessor()
        if rag_processor.vector_store is None:
            # Log clearly but proceed without RAG context if store failed to load/build
            logging.warning(f"[{job_id}] RAG processor initialized without a valid vector store. Norm retrieval will be skipped.")
            # Decide if this should be a fatal error:
            # raise ValueError("Failed to initialize RAG vector store. Cannot proceed.")

        results["status"] = "FINDING_FILES"
        # 3. Find Code Files
        code_files = utils.find_code_files(repo_path)
        results["total_files"] = len(code_files)
        if not code_files:
            results["status"] = "COMPLETED"
            results["message"] = "No code files found matching allowed extensions."
            logging.info(f"[{job_id}] No matching code files found.")
            # No 'return' here, proceed to cleanup

        else:
            results["status"] = "ANALYZING"
            logging.info(f"[{job_id}] Found {len(code_files)} files to analyze.")
            # 4. Analyze Files (Iterative Step)
            all_findings = []
            for i, file_rel_path in enumerate(code_files):
                # Update status for progress tracking (optional)
                # results["status"] = f"ANALYZING ({i+1}/{results['total_files']})"
                logging.info(f"[{job_id}] Processing file {i+1}/{results['total_files']}: {file_rel_path}")
                try:
                    file_findings = analyze_code_file(repo_path, file_rel_path, rag_processor, llm_type)
                    if file_findings: # Only add if findings exist
                        all_findings.extend(file_findings)
                    results["files_scanned"] += 1
                except Exception as file_error:
                    # Log error for specific file but continue scan
                    logging.error(f"[{job_id}] Error analyzing file {file_rel_path}: {file_error}")
                    # Optionally add file-specific errors to results
                    # results.setdefault("file_errors", []).append({"file": file_rel_path, "error": str(file_error)})


            results["findings"] = all_findings
            results["status"] = "COMPLETED"
            logging.info(f"[{job_id}] Scan completed. Found {len(all_findings)} total findings in {results['files_scanned']} files.")

    except Exception as e:
        logging.exception(f"[{job_id}] Critical error during scan: {e}") # Log full traceback
        results["status"] = "FAILED"
        results["error"] = str(e)

    finally:
        # 5. Cleanup
        if repo_path:
            utils.cleanup_repo(repo_path)

        end_time = time.time()
        results["duration_seconds"] = round(end_time - start_time, 2)
        logging.info(f"[{job_id}] Job finished. Status: {results['status']}. Duration: {results['duration_seconds']}s")

    return results
