import logging
import re
import time
import config
import json

# LLM Clients
from openai import OpenAI, RateLimitError, APIError, OpenAIError
import ollama # Official Ollama client

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Constants ---
MAX_RETRIES = 3
RETRY_DELAY = 5 # seconds

# --- LLM Client Initialization ---

def get_openai_client():
    """Initializes and returns the OpenAI client."""
    if not config.OPENAI_API_KEY:
        logging.error("OpenAI API Key not found in configuration.")
        return None
    try:
        client = OpenAI(api_key=config.OPENAI_API_KEY)
        # Test connection (optional, but good practice)
        client.models.list()
        logging.info("OpenAI client initialized successfully.")
        return client
    except APIError as e:
        logging.error(f"OpenAI API Error during initialization: {e}")
        return None
    except OpenAIError as e:
        logging.error(f"OpenAI general error during initialization: {e}")
        return None

def get_ollama_client():
    """Initializes and returns the Ollama client."""
    # Use configured base URL consistently
    ollama_host = config.OLLAMA_BASE_URL
    try:
        client = ollama.Client(host=ollama_host)
        # Test connection and get model list ONCE
        model_list_response = client.list()
        logging.info(f"Ollama client initialized successfully for host {ollama_host}.")

        # --- Robustly extract model names (Updated Check) ---
        available_models = []
        # Check if 'models' key exists and is a list
        if 'models' in model_list_response and isinstance(model_list_response.get('models'), list):
            for m in model_list_response['models']:
                # <<< FIX: Check if 'm' has a 'model' attribute >>>
                if hasattr(m, 'model') and isinstance(m.model, str):
                    available_models.append(m.model) # <<< FIX: Access the 'model' attribute >>>
                else:
                    # Log the entry if it doesn't have the expected structure
                    logging.warning(f"Skipping entry without 'model' attribute in Ollama list response: {m}")
        else:
             logging.warning(f"Ollama list response did not contain a valid 'models' list: {model_list_response}")
        # --- End of robust extraction ---

        # Check if the desired model exists locally
        # Ensure config.OLLAMA_MODEL_NAME is treated as a string
        desired_model_name = str(config.OLLAMA_MODEL_NAME)
        # The model name in .env might or might not include the tag, Ollama list usually includes it.
        # We check if the exact name from config OR the name without a potential tag exists.
        # Note: Ollama list usually returns names WITH tags like 'llama3:latest' or 'deepseek-r1:8b'

        found = False
        if desired_model_name in available_models:
            found = True
        # If the desired name didn't include a tag, check if a ':latest' version exists
        elif ':' not in desired_model_name and f"{desired_model_name}:latest" in available_models:
             found = True
             logging.info(f"Found '{desired_model_name}:latest' for configured model '{desired_model_name}'.")
             # Optional: Update model_name used later if needed, but usually Ollama handles 'model' vs 'model:latest'
             # config.OLLAMA_MODEL_NAME = f"{desired_model_name}:latest"

        if not found:
             logging.warning(f"Ollama model '{desired_model_name}' not found locally. Available models: {available_models}. Make sure it's pulled (`ollama pull {desired_model_name}`).")
             # Depending on policy, you might want to raise an error here or proceed cautiously.
             # return None # Or raise an error if model must exist

        return client
    except Exception as e:
        # Log the specific host URL attempted
        logging.error(f"Failed to initialize Ollama client or connect to {ollama_host}: {e}")
        # Log the full exception traceback for better debugging
        logging.exception("Full exception details during Ollama client initialization:")
        return None

# --- Unified LLM Interaction ---

def generate_completion(llm_type: str, prompt: str, system_prompt: str = None) -> str | None:
    """
    Generates a completion using the specified LLM type.

    Args:
        llm_type: 'openai' or 'ollama'.
        prompt: The main user prompt/query.
        system_prompt: An optional system message for context/instructions.

    Returns:
        The LLM's response content as a string, or None if an error occurs.
    """
    logging.debug(f"Generating completion using {llm_type}")
    client = None
    model_name = ""

    if llm_type == 'openai':
        client = get_openai_client()
        model_name = config.OPENAI_MODEL_NAME
        if not client: return None # Error logged in get_openai_client
    elif llm_type == 'ollama':
        client = get_ollama_client()
        model_name = config.OLLAMA_MODEL_NAME
        if not client: return None # Error logged in get_ollama_client
    else:
        logging.error(f"Unsupported LLM type: {llm_type}")
        return None

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    for attempt in range(MAX_RETRIES):
        try:
            if llm_type == 'openai':
                response = client.chat.completions.create(
                    model=model_name,
                    messages=messages,
                    # Consider adding temperature, max_tokens etc. if needed
                    # response_format={ "type": "json_object" } # If you want guaranteed JSON (GPT-4 Turbo+)
                )
                content = response.choices[0].message.content
                logging.debug(f"OpenAI Response: {content[:100]}...")
                return content.strip()

            elif llm_type == 'ollama':
                # Ollama client uses a slightly different structure
                ollama_response = client.chat(
                    model=model_name,
                    messages=messages,
                    # Ollama supports format='json' for some models
                    # format='json' # Uncomment if your Ollama model supports JSON mode reliably
                )
                content = ollama_response['message']['content']
                logging.debug(f"Ollama Response: {content[:100]}...")
                return content.strip()

        except RateLimitError as e:
            logging.warning(f"Rate limit exceeded (Attempt {attempt + 1}/{MAX_RETRIES}). Retrying in {RETRY_DELAY}s... Error: {e}")
            time.sleep(RETRY_DELAY)
        except APIError as e:
            logging.error(f"API Error from {llm_type} (Attempt {attempt + 1}/{MAX_RETRIES}): {e}")
            # Decide if retryable based on status code if needed
            if attempt == MAX_RETRIES - 1: return None
            time.sleep(RETRY_DELAY)
        except (OpenAIError, ollama.ResponseError, Exception) as e: # Catch Ollama specific errors and general exceptions
            logging.error(f"Error during {llm_type} completion (Attempt {attempt + 1}/{MAX_RETRIES}): {e}")
            if attempt == MAX_RETRIES - 1: return None # Failed after retries
            time.sleep(RETRY_DELAY) # Wait before retrying other errors

    logging.error(f"Failed to get completion from {llm_type} after {MAX_RETRIES} retries.")
    return None


def parse_llm_response_to_json(response_text: str) -> list | dict | None:
    """
    Attempts to parse the LLM's text response, expecting JSON.
    Handles cases where the response might contain markdown code fences (```json ... ```)
    or might just be raw JSON.
    """
    if not response_text:
        return None

    # Try finding JSON within markdown code blocks
    match = re.search(r"```(json)?\s*([\s\S]*?)\s*```", response_text, re.IGNORECASE)
    if match:
        json_str = match.group(2).strip()
    else:
        # Assume the whole response might be JSON, or JSON might start somewhere
        # Find the first '{' or '[' to potentially trim leading text
        start_brace = response_text.find('{')
        start_bracket = response_text.find('[')

        if start_brace == -1 and start_bracket == -1:
             logging.warning("Could not find JSON start characters '{' or '[' in LLM response.")
             return None # No JSON structure found

        if start_brace != -1 and (start_bracket == -1 or start_brace < start_bracket):
            json_str = response_text[start_brace:]
        elif start_bracket != -1:
             json_str = response_text[start_bracket:]
        else: # Should not happen based on above logic, but for safety
             json_str = response_text

        # Attempt to find the matching closing brace/bracket (simple heuristic)
        # This is NOT a robust JSON parser, but helps trim trailing text.
        # A more robust approach would use a JSON parsing library that can handle partial data or errors.
        # For simplicity, we'll just try parsing directly.

    try:
        # Ensure json_str is not empty after potential trimming
        if not json_str:
            logging.warning("Extracted JSON string is empty.")
            return None
        parsed_json = json.loads(json_str)
        return parsed_json
    except json.JSONDecodeError as e:
        logging.error(f"Failed to decode JSON from LLM response: {e}")
        logging.debug(f"Problematic JSON string (approx): {json_str[:500]}...") # Log part of the string
        return None
    except Exception as e:
        logging.error(f"An unexpected error occurred during JSON parsing: {e}")
        return None

