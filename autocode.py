import os
import sys
import logging
import re
from pathlib import Path
import time
from openai import OpenAI

# ==============================
#         CONFIGURATION
# ==============================

USE_BLACKLIST = True  # Set to False to use whitelist mode

# Blacklist Configuration. Only applicable when USE_BLACKLIST is True
EXCLUDE_DIRS = [
    "node_modules/",
    # Add more directories to exclude as needed
]

# Whitelist Configuration. Only applicable when USE_BLACKLIST is False
EXCLUDE_FILES = [
    "package-lock.json",
    # Add more file paths to exclude as needed
]

EXCLUDE_EXTENSIONS = [
    ".log",
    ".tmp",
    ".pyc",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".bmp",
    ".svg",
    ".ico",
    ".pdf",
    ".zip",
    ".tar",
    ".gz",
    ".rar",
    ".7z",
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".bin",
    ".dat",
    ".iso",
    # Add more extensions as needed
]

# Whitelist Configuration. Only applicable when USE_BLACKLIST is False
INCLUDE_DIRS = [
    "src",  # Example: Include only the 'src' directory
    # Add more directories to include as needed
]

# Whitelist Configuration. Only applicable when USE_BLACKLIST is False
INCLUDE_FILES = [
    # Add specific file paths to include if needed
]

# ----- OpenAI API Settings -----
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") or "" # Source from .env or add your key here
GPT_MODEL = "gpt-4o-mini"
GPT_MAX_RETRIES = 3
GPT_TEMPERATURE = 0.2
GPT_MAX_TOKENS = 3000

# ----- GPT System Message -----
GPT_SYSTEM_MESSAGE = (
    "You are a programmer that can modifies code based on user instructions. "
    "For files that you modify, print the entire file with the changes. "
    "Do not add code comments that describe changes."
)

# ----- Logging Settings -----
BASIC_LOG_FILE = "gpt.basic.log"
VERBOSE_LOG_FILE = "gpt.verbose.log"
LOG_LEVEL_BASIC = logging.INFO
LOG_LEVEL_VERBOSE = logging.DEBUG
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"

# ----- File Processing Settings -----
ROOT_DIRECTORY = "."  # Root directory to start processing files


# ==============================
#           FUNCTIONS
# ==============================

def setup_logging():
    """
    Configure the logging settings with two separate log files:
    - gpt.basic.log for basic logs
    - gpt.verbose.log for detailed logs
    """
    # Create a root logger
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)  # Set to lowest level to capture all logs

    # Formatter
    formatter = logging.Formatter(LOG_FORMAT)

    # Basic File Handler
    basic_handler = logging.FileHandler(BASIC_LOG_FILE)
    basic_handler.setLevel(LOG_LEVEL_BASIC)
    basic_handler.setFormatter(formatter)
    logger.addHandler(basic_handler)

    # Verbose File Handler
    verbose_handler = logging.FileHandler(VERBOSE_LOG_FILE)
    verbose_handler.setLevel(LOG_LEVEL_VERBOSE)
    verbose_handler.setFormatter(formatter)
    logger.addHandler(verbose_handler)

    # Stream Handler (Console)
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(LOG_LEVEL_BASIC)  # Adjust as needed
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

def read_file_content(file_path):
    """
    Read the content of a file and return it as a string.
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        logging.error(f"File {file_path} not found.")
        return None
    except UnicodeDecodeError:
        logging.error(f"File {file_path} is a binary file or contains invalid characters. Skipping.")
        return None
    except Exception as e:
        logging.error(f"Error reading {file_path}: {str(e)}")
        return None

def write_file_content(file_path, content):
    """
    Write the given content to a file, ensuring it ends with a newline.
    """
    try:
        if not content.endswith('\n'):
            content += '\n'
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        logging.info(f"Successfully wrote to {file_path}")
    except Exception as e:
        logging.error(f"Error writing to {file_path}: {str(e)}")

def get_all_files(root_dir, exclude_dirs=None, exclude_files=None, include_dirs=None, include_files=None, use_blacklist=True):
    """
    Recursively get all file paths from the root directory, excluding or including specified directories and files.
    """
    all_files = []
    exclude_dirs = [os.path.normpath(path) for path in (exclude_dirs or [])]
    exclude_files = [os.path.normpath(path) for path in (exclude_files or [])]
    include_dirs = [os.path.normpath(path) for path in (include_dirs or [])]
    include_files = [os.path.normpath(path) for path in (include_files or [])]

    for dirpath, dirnames, filenames in os.walk(root_dir):
        # Normalize the current directory path relative to root_dir
        rel_dir = os.path.relpath(dirpath, root_dir)
        if rel_dir == ".":
            rel_dir = ""

        # Handle Blacklist or Whitelist Mode
        if use_blacklist:
            # Exclude directories
            dirnames[:] = [d for d in dirnames if os.path.normpath(os.path.join(rel_dir, d)) not in exclude_dirs]
        else:
            # Whitelist Mode: Only include specified directories
            dirnames[:] = [d for d in dirnames if os.path.normpath(os.path.join(rel_dir, d)) in include_dirs or not include_dirs]

        for filename in filenames:
            file_rel_path = os.path.normpath(os.path.join(rel_dir, filename))

            if use_blacklist:
                # Exclude files in excluded directories or specific excluded files
                if any(file_rel_path.startswith(excl_dir + os.sep) for excl_dir in exclude_dirs):
                    continue
                if file_rel_path in exclude_files:
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

def get_files_to_process(root_directory, use_blacklist=True):
    """
    Determine which files to process based on blacklist or whitelist.
    """
    if use_blacklist:
        files = get_all_files(
            root_directory,
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
            root_directory,
            include_dirs=INCLUDE_DIRS,
            include_files=INCLUDE_FILES,
            use_blacklist=False
        )

        logging.info(f"Using whitelist mode with {len(files)} specified files.")

    existing_files = []
    for file_path in files:
        absolute_path = os.path.join(root_directory, file_path)
        if os.path.isfile(absolute_path):
            existing_files.append(file_path)
        else:
            logging.warning(f"File {file_path} does not exist. Skipping.")

    logging.info(f"Existing files to process: {len(existing_files)}")

    return existing_files

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

def call_gpt_api(prompt, files_content, model=GPT_MODEL, max_retries=GPT_MAX_RETRIES):
    """
    Call the OpenAI GPT API with the given prompt and files content.
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
            return response.choices[0].message.content
        except Exception as e:
            logging.error(f"Error during API call: {e}. Retrying after delay...")
            logging.debug(f"Exception details: {e}")

        wait_time = 2 ** attempt
        logging.info(f"Waiting for {wait_time} seconds before retrying...")
        time.sleep(wait_time)

    logging.critical("Failed to get a response from OpenAI API after multiple attempts.")
    sys.exit(1)

def parse_gpt_response(response_text):
    """
    Parse the GPT response to extract modified code for each file.
    """
    pattern = r"### File: (?P<file>.+?)\n```(?P<language>\w+)?\n(?P<code>.*?)\n```"
    matches = re.finditer(pattern, response_text, re.DOTALL)
    modified_files = {}
    for match in matches:
        raw_file_path = match.group("file").strip()
        file_path = os.path.normpath(raw_file_path)
        code = match.group("code")
        modified_files[file_path] = code
        logging.debug(f"Parsed modification for file: {file_path}")

    logging.info(f"Total modified files parsed: {len(modified_files)}")
    return modified_files

# ==============================
#             MAIN
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
    gpt_response = call_gpt_api(prompt, files_content)

    logging.info("Parsing GPT response...")
    modified_files = parse_gpt_response(gpt_response)

    if not modified_files:
        logging.warning("No modifications received from GPT. Exiting.")
        return

    for file_path, new_content in modified_files.items():
        if file_path in files_content:
            absolute_path = os.path.join(ROOT_DIRECTORY, file_path)
            write_file_content(absolute_path, new_content)
            logging.info(f"File {file_path} has been updated.")
            logging.debug(f"Updated content for {file_path}:\n{new_content}")
        else:
            logging.warning(f"Received modification for unknown file {file_path}. Skipping.")

    logging.info("All applicable files have been processed and updated.")

if __name__ == "__main__":
    main()
