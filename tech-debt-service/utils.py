import os
import git
import shutil
import logging
import uuid
from pathlib import Path
import config

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def generate_job_id():
    """Generates a unique job ID."""
    return str(uuid.uuid4())

def clone_repo(repo_url: str, job_id: str) -> str | None:
    """Clones a Git repository to a unique directory."""
    target_dir = os.path.join(config.REPO_CLONE_DIR, job_id)
    if os.path.exists(target_dir):
        logging.warning(f"Target directory {target_dir} already exists. Removing.")
        shutil.rmtree(target_dir)

    logging.info(f"Cloning {repo_url} to {target_dir}...")
    try:
        git.Repo.clone_from(repo_url, target_dir)
        logging.info(f"Successfully cloned {repo_url}")
        return target_dir
    except git.GitCommandError as e:
        logging.error(f"Error cloning repository {repo_url}: {e}")
        # Clean up failed clone attempt
        if os.path.exists(target_dir):
            shutil.rmtree(target_dir)
        return None
    except Exception as e:
        logging.error(f"An unexpected error occurred during cloning: {e}")
        if os.path.exists(target_dir):
            shutil.rmtree(target_dir)
        return None


def cleanup_repo(repo_path: str):
    """Removes the cloned repository directory."""
    if repo_path and os.path.exists(repo_path):
        logging.info(f"Cleaning up repository at {repo_path}")
        try:
            shutil.rmtree(repo_path)
        except OSError as e:
            logging.error(f"Error removing directory {repo_path}: {e}")
    else:
        logging.warning(f"Attempted to clean up non-existent path: {repo_path}")


def find_code_files(repo_path: str) -> list[str]:
    """Finds all files matching allowed extensions in the repo."""
    code_files = []
    allowed_exts = tuple(config.ALLOWED_EXTENSIONS)
    logging.info(f"Scanning for files with extensions: {allowed_exts} in {repo_path}")

    if not os.path.isdir(repo_path):
        logging.error(f"Repository path {repo_path} does not exist or is not a directory.")
        return []

    for root, _, files in os.walk(repo_path):
        # Skip .git directory
        if '.git' in root.split(os.sep):
            continue
        for file in files:
            if file.lower().endswith(allowed_exts):
                full_path = os.path.join(root, file)
                # Convert to relative path for cleaner reporting
                relative_path = os.path.relpath(full_path, repo_path)
                code_files.append(relative_path) # Store relative path

    logging.info(f"Found {len(code_files)} code files.")
    return code_files

def read_file_content(repo_base_path: str, relative_file_path: str) -> str | None:
    """Reads the content of a specific file."""
    full_path = os.path.join(repo_base_path, relative_file_path)
    try:
        with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read()
    except FileNotFoundError:
        logging.error(f"File not found: {full_path}")
        return None
    except Exception as e:
        logging.error(f"Error reading file {full_path}: {e}")
        return None

