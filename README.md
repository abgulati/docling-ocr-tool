# Docling OCR Directory Processor

## Introduction

This utility provides a powerful, file-based workflow to perform Optical Character Recognition (OCR) on an entire directory of documents using the [Docling](https://docling-project.github.io/docling/) library.  OCR results and configuration settings are persisted locally for ease of use and repeatability.

The script is designed to be highly configurable and resilient, handling various document formats and providing detailed control over the OCR process.

**Key Features 📝**

- Batch Processing: OCR all files placed within a designated `staging` directory.

- Format Conversion: Automatically converts non-PDF files (e.g., DOCX, PPTX) to PDF using `unoconv` before processing.

- Persistent Configuration: On the first run, a `docling_parser_config.json` file is generated. All settings, whether set via command-line arguments or modified directly in the JSON, are saved for subsequent runs.

- Flexible Execution: Run the utility by simply double-clicking the script to use saved settings, or run it from the command line with arguments for one-time configuration changes.

- Rich Output: The utility generates multiple output formats for maximum flexibility:

    - `.txt`: Text file comprising markdown-formatted output from the document

    - `.xml`: An XML representation of the Markdown structure, useful for programmatic parsing.

- Detailed Logging: Errors are captured in a rotating log file (`docling_parser_log.log`) for easy debugging.

## Prerequisites 🛠️

1. `Python`: This utility was built and tested with [Python v3.11.5](https://www.python.org/downloads/release/python-3115/).

2. `LibreOffice`: This utility relies on `unoconv` to convert documents like `.docx` or `.pptx` into PDF format before processing. You must have a compatible office suite (like LibreOffice) installed and available in your system's PATH - Only PDFs are supported if this setup is not completed!

    - Tested and built with `LibreOffice v25.2.5.2 (x86_64)`

    - Windows:
        - Download from the [Official Site](https://www.libreoffice.org/download/download-libreoffice/)

        - Add to PATH, either via:

            - Advanced System Settings -> Environment Variables -> System Variables -> EDIT PATH Variable -> Add the below (change as per your installation location):    
                ```
                C:\Program Files\LibreOffice\program
                ```
            
            - Or via PowerShell:   
                ```
                Set PATH=%PATH%;C:\Program Files\LibreOffice\program
                ```

    - Ubuntu & Debian-based Linux - Download from the [Official Site](https://www.libreoffice.org/download/download-libreoffice/) or install via terminal:

        ```
        sudo apt-get update
        sudo apt-get install -y libreoffice
        ```

    - Fedora and other RPM-based distros - Download from the [Official Site](https://www.libreoffice.org/download/download-libreoffice/) or install via terminal:

        ```
        sudo dnf update
        sudo dnf install libreoffice
        ```

    - MacOS - Download from the [Official Site](https://www.libreoffice.org/download/download-libreoffice/) or install via Homebrew:

        ```
        brew install --cask libreoffice
        ```

    - Verify Installation:
        - On Windows and MacOS: Run the LibreOffice application
        
        - On Linux via the terminal: 
            ```
            libreoffice --version
            ```

## Installation

This utility was built and tested with Python v3.11.5.

1. **Create a Python Virtual Environment:** It's highly recommended to create a virtual environment to manage dependencies and avoid conflicts with other projects.

    ```
    # For Windows
    python -m venv docling-venv
    .\docling-venv\Scripts\activate

    # For macOS/Linux
    python3 -m venv docling-venv
    source docling-venv/bin/activate
    ```

2. **Install Requirements:** Install all the necessary Python packages from the `requirements.txt` file.

    ```
    pip install -r requirements.txt
    ```

## First Run

The first time you run the script, it will automatically set up its working environment.

1. **Execute the Script:** Simply double-click the `.py` file or run `python your_script_name.py` from your terminal.

2. **Auto-Configuration:** The script will create:

    - A configuration file: `docling_parser_config.json`

    - An application directory structure:
        ```
        ./app/docling_parser_storage/
        ├── upload_staging/
        ├── converted_pdfs/
        └── ocr_pdfs/
        ```

3. **Add Files:** Place all the documents you wish to OCR into the newly created `upload_staging` folder.

## Usage

You can run the utility in two primary ways:

**1. Simple Execution (GUI)**
Double-click the Python script file. It will automatically find the files in the `upload_staging` directory and process them using the settings currently saved in `docling_parser_config.json`. This is the easiest method for repeated runs with the same configuration.

**2. Advanced Execution (CLI)**
Run the script from your terminal to override saved settings using command-line arguments. This is ideal for testing different configurations without permanently changing the `docling_parser_config.json` file. Any arguments you provide will be used for that specific run and will be saved as the new default in the config file.

**Example:**
```
python your_script_name.py --dl-ocr-model tesseract --dl-table-structure-mode fast --force-re-extract
```

## Command-Line Arguments
The following arguments can be used to control the utility's behavior:

| Argument               | Description                                                                  | Default Value                                 |
| ---------------------- | ---------------------------------------------------------------------------- | --------------------------------------------- |
| `\--reset_to_defaults` | Resets `docling_parser_config.json` to the script's default settings.        | `FALSE`                                       |
| `\--upload-dir`        | Specifies the input directory for files to be processed.                     | `./app/docling_parser_storage/upload_staging` |
| `\--converted-pdfs`    | The directory where non-PDF files are stored after conversion.               | `./app/docling_parser_storage/converted_pdfs` |
| `\--ocr-pdfs`          | The output directory for all generated `.txt`, `.md`, and `.xml` files.      | `./app/docling_parser_storage/ocr_pdfs`       |
| `\--ocr-service`       | The OCR service to use. Currently only supports `docling`.                   | `docling`                                     |
| `\--force-re-extract`  | If set, forces the script to re-process files even if output already exists. | `FALSE`                                       |


### Docling Specific Arguments
These arguments control the behavior of the Docling OCR engine:

| Argument                           | Description                                                                                         | Default Value              |
| ---------------------------------- | --------------------------------------------------------------------------------------------------- | -------------------------- |
| `\--dl-pipeline`                   | The Docling pipeline to use. Options: `standard`, `vlm`.                                            | `standard`                 |
| `\--dl-vlm-model`                  | The Vision Language Model (VLM) to use with the `vlm` pipeline.                                     | `smoldocling_transformers` |
| `\--dl-ocr-model`                  | The underlying OCR model for the standard pipeline. Options: `easyocr`, `tesseract`, `ocrmac`, etc. | `easyocr`                  |
| `\--dl-do-ocr`                     | A flag to enable or disable the OCR step.                                                           | `TRUE`                     |
| `\--dl-do-code-enrichment`         | A flag to enable special processing for code blocks.                                                | `FALSE`                    |
| `\--dl-do-formula-enrichment`      | A flag to enable special processing for mathematical formulas.                                      | `FALSE`                    |
| `\--dl-do-table-structure`         | A flag to enable detailed table structure recognition.                                              | `TRUE`                     |
| `\--dl-do-picture-classification`  | A flag to enable classification of images within the document.                                      | `FALSE`                    |
| `\--dl-do-picture-description`     | A flag to enable AI-powered descriptions of images.                                                 | `FALSE`                    |
| `\--dl-table-structure-mode`       | The mode for table recognition. Options: `accurate` or `fast`.                                      | `accurate`                 |
| `\--dl-do-cell-matching`           | A flag to enable matching of cells to headers in tables.                                            | `TRUE`                     |
| `\--dl-cuda-use-flash-attention-2` | (For NVIDIA GPUs) A flag to enable Flash Attention 2 for better performance.                        | `FALSE`                    |
| `\--dl-force-full-page-ocr`        | Forces OCR to run on the entire page, ignoring existing text layers.                                | `FALSE`                    |
| `\--dl-num-threads`                | The number of CPU threads to use for processing.                                                    | `4`                        |

**NOTE:** 

- Find a full up-to-date list of CLI options in the official Docling CLI Reference [here](https://docling-project.github.io/docling/reference/cli/)

- A full list of supported VLMs can be found in the `vlm_model_specs.py` [file](https://github.com/docling-project/docling/blob/e76298c40d9a860fe5c8e2d5922397eed4a71763/docling/datamodel/vlm_model_specs.py)

- Feel free to contribute or open an issue to request support for additional flags!