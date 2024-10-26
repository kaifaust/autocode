import os
import sys
import logging
import re
from pathlib import Path
import time
from openai import OpenAI
import shutil

# ==============================
#           CONFIGURATION
# ==============================

ROOT_DIRECTORY = '.'
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
GPT_MODEL = 'gpt-4o-mini'
GPT_MAX_TOKENS = 3000
GPT_TEMPERATURE = 0.2
COST_PER_INPUT_TOKEN = 2.50 / 1000000 # $2.50 per 1M input tokens
COST_PER_OUTPUT_TOKEN = 10.00 / 1000000 # $10.00 per 1M output tokens
USE_BLACKLIST = True
EXCLUDE_DIRS = ['.git', 'node_modules']
EXCLUDE_FILES = ['package-lock.json', 'autocode.py']
EXCLUDE_EXTENSIONS = ['.log', '.png']
INCLUDE_DIRS = []
INCLUDE_FILES = []

# System message for GPT
GPT_SYSTEM_MESSAGE = """You are an artificial intelligence agent that codes.
"""

# ==============================
#            LOGGING
# ==============================

def setup_logging():
    logging.basicConfig(
        filename='gpt.log',
        level=logging.DEBUG,
        format='%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
    console.setFormatter(formatter)
    logging.getLogger('').addHandler(console)

# ==============================
#          FILE HANDLING
# ==============================

def read_file_content(file_path):
    """
    Read the content of a file. Returns None if there's an error.
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        return content
    except Exception as e:
        logging.error(f"Error reading {file_path}: {str(e)}")
        return None

def write_file_content(file_path, content):
    """
    Write content to a file. Creates the file if it doesn't exist.
    """
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        logging.info(f"Successfully wrote to {file_path}")
    except Exception as e:
        logging.error(f"Error writing to {file_path}: {str(e)}")

# ==============================
#        FILE FILTERING
# ==============================

def get_all_files(ROOT_DIRECTORY, exclude_dirs=None, exclude_files=None, include_dirs=None, include_files=None, use_blacklist=True):
    """
    Recursively get all file paths under ROOT_DIRECTORY.
    Apply exclusion or inclusion based on the mode.
    """
    all_files = []
    for dirpath, dirnames, filenames in os.walk(ROOT_DIRECTORY):
        # Compute relative path from ROOT_DIRECTORY
        rel_dir = os.path.relpath(dirpath, ROOT_DIRECTORY)
        if rel_dir == '.':
            rel_dir = ''

        # Exclude directories if in blacklist mode
        if use_blacklist and exclude_dirs:
            dirnames[:] = [d for d in dirnames if os.path.join(rel_dir, d) not in exclude_dirs]

        # Include only specified directories if in whitelist mode
        if not use_blacklist and include_dirs:
            dirnames[:] = [d for d in dirnames if os.path.join(rel_dir, d) in include_dirs]

        for filename in filenames:
            file_rel_path = os.path.normpath(os.path.join(rel_dir, filename))
            if use_blacklist:
                # Blacklist Mode: Exclude specified directories or files
                if exclude_files and file_rel_path in exclude_files:
                    continue
                if exclude_dirs and any(file_rel_path.startswith(inc_dir + os.sep) for inc_dir in exclude_dirs):
                    continue
                # Further filter out files based on excluded extensions
                if EXCLUDE_EXTENSIONS and any(file_rel_path.lower().endswith(ext.lower()) for ext in EXCLUDE_EXTENSIONS):
                    continue
            else:
                # Whitelist Mode: Include only specified directories or files
                if include_dirs and not any(file_rel_path.startswith(inc_dir + os.sep) for inc_dir in include_dirs):
                    continue
                if include_files and file_rel_path not in include_files:
                    continue

            all_files.append(file_rel_path)

    logging.info(f"Total files to process: {len(all_files)}")
    return all_files

def get_files_to_process(ROOT_DIRECTORY, use_blacklist=True):
    """
    Determine which files to process based on blacklist or whitelist.
    """
    if use_blacklist:
        files = get_all_files(
            ROOT_DIRECTORY,
            exclude_dirs=EXCLUDE_DIRS,
            exclude_files=EXCLUDE_FILES,
            use_blacklist=True
        )

        # Further filter out files based on excluded extensions
        files = [
            f for f in files
            if not any(f.lower().endswith(ext.lower()) for ext in EXCLUDE_EXTENSIONS)
        ]

        logging.info(f"Using blacklist mode with {len(files)} files after exclusions.")
    else:
        files = get_all_files(
            ROOT_DIRECTORY,
            include_dirs=INCLUDE_DIRS,
            include_files=INCLUDE_FILES,
            use_blacklist=False
        )

        logging.info(f"Using whitelist mode with {len(files)} specified files.")

    existing_files = []
    for file_path in files:
        absolute_path = os.path.join(ROOT_DIRECTORY, file_path)
        if os.path.isfile(absolute_path):
            existing_files.append(file_path)
        else:
            logging.warning(f"File {file_path} does not exist. Skipping.")

    logging.info(f"Existing files to process: {len(existing_files)}")

    return existing_files

# ==============================
#        USER PROMPT
# ==============================

def get_user_prompt():
    """
    Prompt the user to enter instructions for code changes.
    """
    logging.info("Prompting user for instructions for code changes.")
    print("Enter your instructions for code changes. When done, press Enter on an empty line:")
    lines = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line.strip() == "":
            break
        lines.append(line)
    prompt = "\n".join(lines)
    logging.info("User has provided the code change instructions.")
    return prompt

# ==============================
#      LANGUAGE DETECTION
# ==============================

def get_language(file_path):
    """
    Determine the programming language based on the file extension.
    """
    language_mapping = {
        ".py": "python",
        ".js": "javascript",
        ".ts": "typescript",
        ".tsx": "tsx",
        ".scss": "scss",
        ".css": "css",
        ".html": "html",
        ".jsx": "jsx",
        ".json": "json",
        ".md": "markdown",
        # Add more mappings as needed
    }
    ext = Path(file_path).suffix.lower()
    return language_mapping.get(ext, "")

# ==============================
#        GPT API CALL
# ==============================

def call_gpt_api(prompt, files_content, model=GPT_MODEL, max_retries=5):
    """
    Call the OpenAI GPT API with the given prompt and files content.
    Returns the response text and token usage.
    """
    if not OPENAI_API_KEY:
        logging.error("OPENAI_API_KEY environment variable not set.")
        sys.exit(1)

    client = OpenAI(api_key=OPENAI_API_KEY)

    context = ""
    for file_path, content in files_content.items():
        language = get_language(file_path)
        context += f"### File: {file_path}\n```{language}\n{content}\n```\n\n"

    user_message = (
        f"{prompt}\n\n"
        "Here is the existing codebase:\n\n"
        f"{context}\n\n"
        "Please provide the modified code for each file in the following format:\n\n"
        "### File: <file_path>\n"
        "```<language>\n"
        "<modified_code>\n"
        "```\n\n"
        "If any files need to be deleted, specify them using the following format:\n\n"
        "### DELETE: <file_path>\n"
        "Do not respond to files that do not need to be modified.\n"
        "For files that do not need to be modified, do not respond at all.\n"
        "For files that need to be modified, respond with the entire modified code without truncation or anything less than the entire file.\n"
        "Do not add code comments that describe changes. For example, writing '// Changed the function name' is not allowed."
    )

    logging.debug("Preparing to send the following user message to OpenAI API:")
    logging.debug(user_message)

    for attempt in range(1, max_retries + 1):
        try:
            logging.info(f"Attempting to call OpenAI API (Attempt {attempt}/{max_retries})")
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": GPT_SYSTEM_MESSAGE},
                    {"role": "user", "content": user_message}
                ],
                temperature=GPT_TEMPERATURE,
                max_tokens=GPT_MAX_TOKENS,
            )
            logging.info("Successfully received response from OpenAI API.")
            logging.debug("OpenAI API response:")
            logging.debug(response.choices[0].message.content)
            return response.choices[0].message.content, response.usage
        except Exception as e:
            logging.error(f"Error during API call: {e}. Retrying after delay...")
            logging.debug(f"Exception details: {e}")

        wait_time = 2 ** attempt
        logging.info(f"Waiting for {wait_time} seconds before retrying...")
        time.sleep(wait_time)

    logging.critical("Failed to get a response from OpenAI API after multiple attempts.")
    sys.exit(1)

# ==============================
#        GPT RESPONSE PARSING
# ==============================

def parse_gpt_response(response_text):
    """
    Parse the GPT response to extract modified code for each file and files to delete.
    """
    # Pattern to match modified files
    file_pattern = r"### File: (?P<file>.+?)\n```(?P<language>\w+)?\n(?P<code>.*?)\n```"
    # Updated pattern to match files to delete, anchored to the start of a line
    delete_pattern = r"^### DELETE: (?P<file>.+)$"

    modified_files = {}
    files_to_delete = set()  # Use a set to avoid duplicate deletions

    # Parse modified files
    for match in re.finditer(file_pattern, response_text, re.DOTALL):
        raw_file_path = match.group("file").strip()
        file_path = os.path.normpath(raw_file_path)
        code = match.group("code")
        modified_files[file_path] = code
        logging.debug(f"Parsed modification for file: {file_path}")

    # Parse files to delete
    for match in re.finditer(delete_pattern, response_text, re.MULTILINE):
        raw_file_path = match.group("file").strip()
        file_path = os.path.normpath(raw_file_path)
        files_to_delete.add(file_path)  # Add to set to ensure uniqueness
        logging.debug(f"Parsed deletion instruction for file: {file_path}")

    logging.info(f"Total modified files parsed: {len(modified_files)}")
    logging.info(f"Total files to delete parsed: {len(files_to_delete)}")
    return modified_files, list(files_to_delete)

# ==============================
#          DELETE FILES
# ==============================

def delete_files(ROOT_DIRECTORY, files_to_delete):
    """
    Delete the specified files or directories from the filesystem.
    """
    for file_path in files_to_delete:
        absolute_path = os.path.join(ROOT_DIRECTORY, file_path)
        if os.path.isfile(absolute_path):
            try:
                os.remove(absolute_path)
                logging.info(f"Deleted file: {file_path}")
            except Exception as e:
                logging.error(f"Error deleting file {file_path}: {str(e)}")
        elif os.path.isdir(absolute_path):
            try:
                shutil.rmtree(absolute_path)
                logging.info(f"Deleted directory and its contents: {file_path}")
            except Exception as e:
                logging.error(f"Error deleting directory {file_path}: {str(e)}")
        else:
            logging.warning(f"File or directory to delete does not exist: {file_path}")

# ==============================
#            MAIN
# ==============================

def main():
    setup_logging()

    logging.info("Starting the code modification script.")
    files_to_process = get_files_to_process(ROOT_DIRECTORY, use_blacklist=USE_BLACKLIST)

    if not files_to_process:
        logging.warning("No files to process. Exiting.")
        return

    files_content = {}
    for file_path in files_to_process:
        absolute_path = os.path.join(ROOT_DIRECTORY, file_path)
        content = read_file_content(absolute_path)
        if content is not None:
            files_content[file_path] = content
            logging.debug(f"Read content from {file_path}")

    if not files_content:
        logging.error("No file contents to process. Exiting.")
        return

    prompt = get_user_prompt()
    if not prompt.strip():
        logging.warning("No prompt provided. Exiting.")
        return

    logging.info("Calling OpenAI GPT API to process code changes...")
    gpt_response, usage = call_gpt_api(prompt, files_content)

    logging.info("Parsing GPT response...")
    modified_files, files_to_delete = parse_gpt_response(gpt_response)

    # Process file deletions
    if files_to_delete:
        logging.info("Processing file deletions as per GPT instructions...")
        delete_files(ROOT_DIRECTORY, files_to_delete)
    else:
        logging.info("No files to delete as per GPT instructions.")

    # Update files with modified content
    if modified_files:
        for file_path, new_content in modified_files.items():
            if file_path in files_content:
                absolute_path = os.path.join(ROOT_DIRECTORY, file_path)
                write_file_content(absolute_path, new_content)
                logging.info(f"File {file_path} has been updated.")
                logging.debug(f"Updated content for {file_path}:\n{new_content}")
            else:
                logging.warning(f"Received modification for unknown file {file_path}. Skipping.")
    else:
        logging.info("No file modifications received from GPT.")

    logging.info("All applicable files have been processed and updated.")

    # ----- Cost Estimation -----
    if usage is not None:
        prompt_tokens = getattr(usage, 'prompt_tokens', 0)
        completion_tokens = getattr(usage, 'completion_tokens', 0)

        cost_input = prompt_tokens * COST_PER_INPUT_TOKEN
        cost_output = completion_tokens * COST_PER_OUTPUT_TOKEN
        total_cost = cost_input + cost_output

        # Format the cost to two decimal places
        formatted_cost = "${:,.2f}".format(total_cost)

        print(f"\nEstimated cost of this prompt: {formatted_cost}")
        logging.info(f"Estimated cost of this prompt: {formatted_cost}")
    else:
        logging.warning("No usage information available for cost estimation.")

if __name__ == "__main__":
    main()
