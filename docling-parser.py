import subprocess
import threading
import traceback
import platform
import argparse
import logging
import pathlib
import marko
import fitz # PyMuPDF
import json
import sys
import os
import io

from logging.handlers import RotatingFileHandler
from marko.ast_renderer import XMLRenderer

try:
    # Standard Pipeline
    from docling.datamodel.pipeline_options import (
        PdfPipelineOptions, 
        TableFormerMode,
        EasyOcrOptions,
        TesseractOcrOptions,
        TesseractCliOcrOptions,
        OcrMacOptions,
        RapidOcrOptions,
    )

    from docling.datamodel.base_models import DocumentStream, InputFormat
    from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    # VLM Pipeline
    from docling.datamodel.pipeline_options import VlmPipelineOptions
    from docling.datamodel import vlm_model_specs
    from docling.pipeline.vlm_pipeline import VlmPipeline

    from docling_core.types.doc import ImageRefMode
except Exception as e:
    raise Exception(f"Could not import Docling OCR, skipping. If not installed, please run `pip install docling`. Encountered error: {e}")


#########################------------Global & Environment Variables and Semaphores------------###############################
config_writer_semaphore = threading.Semaphore(1)
error_logging_semaphore = threading.Semaphore(1)
reader_semaphore = threading.Semaphore(1)

DOCLING_CONVERTER = None

#########################---------------------------------------------------------------------###############################


#########################------------Setup & Handle Logging-------------###############################
try:
    # 1 - Create a logger
    LOGGER = logging.getLogger('my_logger')
    LOGGER.setLevel(logging.ERROR)

    # 2 - Create a RotatingFileHandler
    # maxBytes: 1024 * 1024 * 5 Bytes = 5MB max file size per log, 2 backups = 3 files total
    handler = RotatingFileHandler('docling_parser_log.log', maxBytes=1024*1024*5, backupCount=2)
    handler.setLevel(logging.ERROR)

    # 3 - Create a formatter and set it for the handler
    formatter = logging.Formatter('%(asctime)s:%(levelname)s:%(message)s')
    handler.setFormatter(formatter)

    # 4 - Add the handler to the logger for final LOGGER - Usage: LOGGER.error(f"This is an error message with error {e}")
    LOGGER.addHandler(handler)
except Exception as e:
    print(f"\n\nCould not establish logger, encountered error: {e}")


def central_error_logging(message:str, exception:Exception=None):
    with error_logging_semaphore:
        error_message = f"\n\n{message} {str(exception) if exception else '; No exception info.'}\n\n"
        
        # traceback.format_exc() is most reliable when called directly from within an except block. If passing an exception object, it's best to handle it more explicitly!
        if exception:
            traceback_details = "".join(traceback.format_exception(type(exception), exception, exception.__traceback__))    # Get traceback of the passed 'exception' object
        else:
            # If no specific exception, format_exc() might give current stack if in an except block, or minimal info
            traceback_details = traceback.format_exc() if sys.exc_info()[0] else "No active exception."
        
        full_message = f"\n\n{error_message}\n\nTraceback: {traceback_details}\n\n"

        if LOGGER:
            LOGGER.error(full_message)
            print(error_message)
        else:
            print(error_message)
    
    return error_message


# For use with Flask APIs:
# def handle_api_error(message, exception=None):
#     error_message = central_error_logging(message, exception)
#     return jsonify(success=False, error=error_message), 500 #internal server error


def handle_local_error(message:str, exception:Exception=None):
    _ = central_error_logging(message, exception)
    raise Exception(exception)


def handle_error_no_return(message:str, exception:Exception=None):
    _ = central_error_logging(message, exception)

#########################-------------------------------------###############################



############################------------configuration manager-------------###############################



if not os.path.exists('docling_parser_config.json'):
    '''
    Initializes an empty JSON configuration file named 'docling_parser_config.json' if it doesn't exist.
    '''
    with config_writer_semaphore:
        try:
            with open('docling_parser_config.json', 'w') as file:
                json.dump({}, file)
        except Exception as e:
            handle_error_no_return("Could not init docling_parser_config.json, encountered error: ", e)


def write_config(config_updates:dict, filename:str='docling_parser_config.json') -> dict:
    '''
    Method to write app configuration to docling_parser_config.json.\n
    Acquires a semaphore to prevent concurrent writes to the file.
    
    Args:
        - config_updates: dict of key:values to be written to docling_parser_config.json
        - filename: name of the file to write to, defaults to 'docling_parser_config.json'

    Returns:
        - Confirmation of success: {success: True}

    Raises:
        - Exception: If the file cannot be written to
    '''

    with config_writer_semaphore:

        # First, open existing config file (if present) to read-in current settings, fallback to an empty dict if file does not exist:
        try:
            with open(filename, 'r') as file:
                config = json.load(file)
        except Exception as e:
            config = {}     #init emply config dict
            handle_error_no_return("Could not read docling_parser_config.json when attempting to write updates, will attempt to create a new file. Encountered error: ", e)

        config.update(config_updates)

        # Write updated config.json:
        try:
            with open(filename, 'w') as file:
                json.dump(config, file, indent=4)
        except Exception as e:
            handle_local_error("Could not update docling_parser_config.json, encountered error: ", e)
        
        return {'success': True}


def safe_write_config(config_updates:dict, filename:str='docling_parser_config.json') -> dict:
    '''
    Wrapper for write-config() that handles errors silently.
    Directly invoke write-config() instead of this method anytime a write-specific error must be raised!
    '''
    try:
        return write_config(config_updates, filename)
    except Exception as e:
        handle_error_no_return("Could not write to docling_parser_config.json, encountered error: ", e)
        return {'success': False}


def read_config(keys:list, default_value=None, filename='docling_parser_config.json') -> dict:
    '''
    Method to read app configuration from docling_parser_config.json.
    Acquires a semaphore to prevent concurrent reads to the file.
    
    Args:
        - keys: list of keys to read from docling_parser_config.json
        - default_value: default value to return if a key is not found in docling_parser_config.json, defaults to None
        - filename: name of the file to read from, defaults to 'docling_parser_config.json'

    Returns:
        - dict of key:values read from docling_parser_config.json

    Raises:
        - KeyError: If a key is not found in docling_parser_config.json and no default value has been defined
    '''

    with reader_semaphore:
    
        try:
            with open(filename, 'r') as file:
                config = json.load(file)
        except Exception as e:
            handle_error_no_return("Could not read docling_parser_config.json, encountered error: ", e)
            return {key: default_value for key in keys}     #because a read scenario wherein docling_parser_config.json does not exist shouldn't occur!
        
        return_dict = {}
        update_config_dict = {}
        base_directory = config.get('base_directory', './app/docling_parser_storage')   # specifying default if not found

        for key in keys:
            if key in config:
                return_dict[key] = config[key]
            else:
                default_value = {
                    'base_directory':base_directory,
                    'upload_staging_folder':base_directory + '/upload_staging',
                    'converted_pdfs':base_directory + '/converted_pdfs',
                    'ocr_pdfs':base_directory + '/ocr_pdfs',
                    'force_re_extract':False,
                    'ocr_service_choice':'docling',
                    'docling_pipeline':'standard',
                    'docling_vlm_model':'smoldocling_transformers',
                    'docling_ocr_model':'easyocr',
                    'docling_do_ocr':True,
                    'docling_do_code_enrichment':False,
                    'docling_do_formula_enrichment':False,
                    'docling_do_table_structure':True,
                    'docling_do_picture_classification':False,
                    'docling_do_picture_description':False,
                    'docling_table_structure_mode':'accurate',
                    'docling_do_cell_matching':True,
                    'docling_cuda_use_flash_attention_2':False,
                    'docling_force_full_page_ocr':False,
                    'docling_num_threads':4
                }.get(key, 'undefined')

                if default_value == 'undefined':
                    raise KeyError(f"Key \'{key}\' not found in docling_parser_config.json and no default value has been defined either.\n")
                
                return_dict[key] = default_value
                update_config_dict[key] = default_value
        
        if update_config_dict: safe_write_config(update_config_dict)   # write defaults to docling_parser_config.json

        return return_dict

############################----------------------------------------------###############################



#########################------------Setup App Directories-------------###############################

try:
    read_return = read_config(['upload_staging_folder', 'ocr_pdfs', 'converted_pdfs'])
except Exception as e:
    handle_local_error("Could not read directory paths from docling_parser_config.json, encountered error: ", e)

try:
    os.makedirs(read_return['upload_staging_folder'], exist_ok=True)
    os.makedirs(read_return['ocr_pdfs'], exist_ok=True)
    os.makedirs(read_return['converted_pdfs'], exist_ok=True)
except Exception as e:
    handle_local_error("Could not create app directories, encountered error: ", e)


#########################----------------------------------------------###############################


def get_xml_from_text(txt_filepath:pathlib.Path) -> pathlib.Path:
    '''
    Convert a text file to an XML file using Marko

    Args:
        - txt_filepath: pathlib.Path object of the text file to be converted

    Returns:
        - pathlib.Path object of the output XML file

    Raises:
        - Exception: If the text file cannot be opened, the output XML file cannot be created, or the conversion fails
    '''

    try:
        print(f"\n\nConverting text file to XML: {txt_filepath}\n\n")

        # 1. Read the file content using pathlib's built-in method
        text_content = txt_filepath.read_text(encoding='utf-8')
        
        # 2. Instantiate the Markdown class, passing the XMLRenderer as the renderer.
        markdown_converter = marko.Markdown(renderer=XMLRenderer)  

        # 3. Call the converter instance with the text - This single call performs both parsing and XML rendering.
        xml_content = markdown_converter(text_content)

        # 4. Write the XML content to a new file using pathlib's built-in method
        xml_filepath = txt_filepath.with_suffix('.xml')
        xml_filepath.write_text(xml_content, encoding='utf-8')
        
        print(f"XML file created successfully: {xml_filepath}")
        return xml_filepath

    except Exception as e:
        handle_local_error("Could not convert text to XML, encountered error: ", e)


def get_docling_ocr_model(model_name_string:str):
    try:
        if model_name_string == 'easyocr':
            return EasyOcrOptions()
        
        if model_name_string == 'tesseract':
            return TesseractOcrOptions()
        
        if model_name_string == 'tesseract_cli':
            return TesseractCliOcrOptions()
        
        if model_name_string == 'ocrmac':
            return OcrMacOptions()
        
        if model_name_string == 'rapidocr':
            return RapidOcrOptions()
        
    except Exception as e:
        handle_local_error("Could not get Docling OCR model, encountered error: ", e)
        

def get_docling_vlm_model(model_name_string:str):
    try:
        if model_name_string == 'smoldocling_mlx':
            return vlm_model_specs.SMOLDOCLING_MLX
        
        if model_name_string == 'smoldocling_transformers':
            return vlm_model_specs.SMOLDOCLING_TRANSFORMERS
        
        if model_name_string == 'granite_vision_transformers':
            return vlm_model_specs.GRANITE_VISION_TRANSFORMERS
        
        if model_name_string == 'granite_vision_ollama':
            return vlm_model_specs.GRANITE_VISION_OLLAMA

        if model_name_string == 'pixtral_12b_transformers':
            return vlm_model_specs.PIXTRAL_12B_TRANSFORMERS
        
        if model_name_string == 'pixtral_12b_mlx':
            return vlm_model_specs.PIXTRAL_12B_MLX
        
        if model_name_string == 'phi4_transformers':
            return vlm_model_specs.PHI4_TRANSFORMERS
        
        if model_name_string == 'qwen25_vl_3b_mlx':
            return vlm_model_specs.QWEN25_VL_3B_MLX
        
        if model_name_string == 'gemma3_12b_mlx':
            return vlm_model_specs.GEMMA3_12B_MLX
        
        if model_name_string == 'gemma3_27b_mlx':
            return vlm_model_specs.GEMMA3_27B_MLX
        
    except Exception as e:
        handle_local_error("Could not get Docling VLM model, encountered error: ", e)


def get_docling_config() -> dict:
    try:
        return read_config(
            [
                'docling_pipeline',
                'docling_vlm_model',
                'docling_ocr_model',
                'docling_do_ocr',
                'docling_do_code_enrichment',
                'docling_do_formula_enrichment',
                'docling_do_table_structure',
                'docling_do_picture_classification',
                'docling_do_picture_description',
                'docling_table_structure_mode',
                'docling_do_cell_matching',
                'docling_cuda_use_flash_attention_2',
                'docling_num_threads',
                'docling_force_full_page_ocr'
            ]
        )
    except Exception as e:
        handle_local_error("Could not read Docling config, encountered error: ", e)


def get_docling_converter(docling_config:dict):
    try:

        if docling_config['docling_pipeline'] == 'vlm':
            
            # a. Set VLM Pipeline Options
            vlm_pipeline_options = None
            vlm_pipeline_options = VlmPipelineOptions()
            vlm_pipeline_options.vlm_options = get_docling_vlm_model(docling_config['docling_vlm_model'])

            # b. VLM Converter
            vlm_converter = DocumentConverter(
                format_options={
                    InputFormat.PDF: PdfFormatOption(
                        pipeline_cls=VlmPipeline,
                        pipeline_options=vlm_pipeline_options,
                    ),
                }
            )

            return vlm_converter

        # Standard Pipeline
        # a. Set PDF Pipeline Options
        pdf_pipeline_options = None
        pdf_pipeline_options = PdfPipelineOptions()
        pdf_pipeline_options.do_ocr = str(docling_config['docling_do_ocr']).lower() == 'true'
        pdf_pipeline_options.do_code_enrichment = str(docling_config['docling_do_code_enrichment']).lower() == 'true'
        pdf_pipeline_options.do_formula_enrichment = str(docling_config['docling_do_formula_enrichment']).lower() == 'true'
        pdf_pipeline_options.do_table_structure = str(docling_config['docling_do_table_structure']).lower() == 'true'
        pdf_pipeline_options.do_picture_classification = str(docling_config['docling_do_picture_classification']).lower() == 'true'
        pdf_pipeline_options.do_picture_description = str(docling_config['docling_do_picture_description']).lower() == 'true'
        pdf_pipeline_options.table_structure_options.mode = TableFormerMode.ACCURATE if str(docling_config['docling_table_structure_mode']) == 'accurate' else TableFormerMode.FAST
        pdf_pipeline_options.table_structure_options.do_cell_matching = str(docling_config['docling_do_cell_matching']).lower() == 'true'
        pdf_pipeline_options.accelerator_options = AcceleratorOptions(
            num_threads = int(docling_config['docling_num_threads']),
            device = AcceleratorDevice.AUTO,
            # cuda_use_flash_attention_2 = str(docling_config['docling_cuda_use_flash_attention_2']).lower() == 'true'
        )

        # b. Set OCR Options
        ocr_options = get_docling_ocr_model(str(docling_config['docling_ocr_model']))
        ocr_options.force_full_page_ocr = str(docling_config['docling_force_full_page_ocr']).lower() == 'true'
        pdf_pipeline_options.ocr_options = ocr_options

        # c. Initialize converter and process
        converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(
                    pipeline_options=pdf_pipeline_options,
                )
            }
        )
        
        return converter

    except Exception as e:
        handle_local_error("Could not get Docling converter, encountered error: ", e)


def docling_ocr_page(page_as_pdf_bytes:bytes, page_number:int, retry_count:int=0) -> str:
    '''
    OCR a single page using Docling
    '''
    global DOCLING_CONVERTER
    try:
        # Create Document-Stream object from bytes
        buf = io.BytesIO(page_as_pdf_bytes)
        source = DocumentStream(name=f"page_{page_number}.pdf", stream=buf)

        # Get Docling converter
        docling_config = get_docling_config()
        DOCLING_CONVERTER = get_docling_converter(docling_config) if DOCLING_CONVERTER is None else DOCLING_CONVERTER

        # Extract text and return the result
        result = DOCLING_CONVERTER.convert(source=source)
        return str(result.document.export_to_markdown(image_mode=ImageRefMode.PLACEHOLDER))

    except Exception as e:
        if retry_count < 3:
            print(f"Retrying Docling OCR for page {page_number}, retry attempt {retry_count+1} of 3. Encountered error: {e}")
            return docling_ocr_page(page_as_pdf_bytes, page_number, retry_count + 1)
        else:
            handle_local_error("Failed to receive a proper response from the Docling OCR service even after 3 retries, stopping execution. Encountered error: ", e)


def PDFtoDoclingOCRTXT(input_pdf_filepath:pathlib.Path) -> pathlib.Path:
    '''
    OCR PDFs using Docling by iterating through each page, converting to a binary stream and then invoking `dolcing_ocr_page()`

    Args:
        - input_pdf_filepath: pathlib.Path object of the PDF file to be OCR'ed

    Returns:
        - pathlib.Path object of the output text file

    Raises:
        - Exception: If the PDF file cannot be opened, the output text file cannot be initialized, or the OCR process fails
    '''

    try:
        read_return = read_config(['force_re_extract', 'ocr_pdfs'])
    except Exception as e:
        handle_local_error("Could not read required values from config.json when attempting to convert PDF to TXT, encountered error: ", e)
    
    try:
        source_filename = input_pdf_filepath.name
        print(f"\n\nApplying Docling OCR to PDF file: {source_filename}\n\n")

        output_text_file_name = input_pdf_filepath.with_suffix(".txt").name
        output_text_file_path = pathlib.Path(rf"{read_return['ocr_pdfs']}").resolve() / output_text_file_name   # normalize and append filename
    except Exception as e:
        handle_local_error("Could not extract filename, encountered error: ", e)

    if output_text_file_path.exists() and not read_return['force_re_extract']:
        if os.path.getsize(output_text_file_path) > 0:
            print(f"Docling OCR'ed doc already exists and is not empty! Returning existing file: {output_text_file_path}")
            return output_text_file_path
        else:
            print(f"Docling OCR'ed doc already exists but is empty! Overwriting with new OCR'ed file: {output_text_file_path}")

    # Open with PyMuPDF for conversion to binary byte stream
    try:
        pdf_document = fitz.open(input_pdf_filepath)
        pdf_document_length = len(pdf_document)
    except Exception as e:
        handle_local_error("Could not open PDF file, encountered error: ", e)
    
    # Initialize text output
    try:
        output_text_file = open(output_text_file_path, 'w', encoding='utf-8')
    except Exception as e:
        handle_local_error("Could not initialize/access output text file, encountered error: ", e)
    
    # Iterate through each page and OCR
    for page_number in range(pdf_document_length):
        try:
            print(f"\nProcessing Page: {page_number + 1} of {pdf_document_length} from file: {source_filename}\n")

            # Extract single page as a new PDF
            single_page_pdf = fitz.open()
            single_page_pdf.insert_pdf(pdf_document, from_page=page_number, to_page=page_number)

            # Convert to bytes
            single_page_pdf_bytes = single_page_pdf.tobytes()
            single_page_pdf.close()

            # Process with Docling
            full_parsed_text = docling_ocr_page(single_page_pdf_bytes, page_number + 1)

            # Write to output file
            output_text_file.write(f"[PAGE:{page_number + 1}]\n{full_parsed_text}\n")

        except Exception as e:
            handle_error_no_return(f"Could not process page {page_number+1} of {pdf_document_length}, encountered error: ", e)
            continue
    
    # Close & return
    output_text_file.close()
    print(f"\n\nCompleted Docling OCR for PDF file: {input_pdf_filepath}\n\n")
    return output_text_file_path


def get_text_extract_from_pdf(pdf_filepath:pathlib.Path) -> pathlib.Path:
    '''
    Determine which OCR service to use and extract text from the PDF document

    Args:
        - pdf_filepath: pathlib.Path object of the PDF file to be OCR'ed

    Returns:
        - pathlib.Path object of the output text file

    Raises:
        - Exception: If the PDF file cannot be opened, the output text file cannot be initialized, or the OCR process fails
    '''

    try:
        read_return = read_config(['ocr_service_choice'])
    except Exception as e:
        handle_local_error("Could not determine force-ocr in config.json. Disabling OCR and proceeding. Error: ", e)
    
    try:
        if read_return['ocr_service_choice'].lower().strip() == 'docling':
            txt_filepath = PDFtoDoclingOCRTXT(pdf_filepath)
        else:
            raise Exception(f"Invalid OCR service choice: {read_return['ocr_service_choice']}")
    except Exception as e:
            handle_local_error("Failed to extract text from the PDF document, encountered error: ", e)
    
    return txt_filepath


def convert_to_pdf_with_unoconv(input_file_path:pathlib.Path, output_file_path:pathlib.Path):
    '''
    Convert a non-PDF document to a PDF file using unoconv

    Args:
        - input_file_path: pathlib.Path object of the input file to be converted
        - output_file_path: pathlib.Path object of the output file to be created
    '''
    print(f"\n\nConverting non-PDF document to PDF format. Input file: {input_file_path}. Output file: {output_file_path}\n\n")
    if platform.system() == 'Windows':
        subprocess.run(['python', 'unoconv.py', '-f', 'pdf', '-o', output_file_path, input_file_path], check=True)
    else:
        subprocess.run(['unoconv', '-f', 'pdf', '-o', output_file_path, input_file_path], check=True)


def prep_and_execute_unoconv_conversion(input_filepath:pathlib.Path, target_dir:pathlib.Path) -> tuple[str, pathlib.Path]:
    '''
    Prepare and execute the unoconv conversion of a non-PDF document to a PDF file

    Args:
        - input_filepath: pathlib.Path object of the input file to be converted
        - target_dir: pathlib.Path object of the directory to save the converted file

    Returns:
        - pathlib.Path object of the output file

    Raises:
        - Exception: If the input file cannot be converted, the output file cannot be created, or the conversion fails
    '''
    print("Converting to PDF file")

    try:
        conv_filename = input_filepath.with_suffix(".pdf").name
        output_filepath = target_dir / conv_filename
        convert_to_pdf_with_unoconv(input_filepath, output_filepath)
        return output_filepath
    except subprocess.CalledProcessError as e:
        handle_local_error("Could not convert file to PDF, encountered error: ", e)
    except Exception as e:
        handle_local_error("Unexpected error when converting file to PDF, encountered error: ", e)


def check_if_converted_file_exists(pdf_filename:str) -> tuple[bool, pathlib.Path]:
    '''
    Invoked for non-PDF files to check if a converted file already exists

    Args:
        - pdf_filename: pathlib.Path object of the PDF file to be checked

    Returns:
        - tuple[bool, pathlib.Path]: True if the converted file exists, False otherwise, and the path to the converted file

    Raises:
        - Exception: If the converted file cannot be found, the output file cannot be created, or the conversion fails
    '''
    try:
        read_return = read_config(['converted_pdfs'])
    except Exception as e:
        handle_local_error("Could not read converted_pdfs from config.json, encountered error: ", e)

    try:
        pdf_filepath = pathlib.Path(rf"{read_return['converted_pdfs']}").resolve() / pdf_filename
        return pdf_filepath.exists(), pdf_filepath
    except Exception as e:
        handle_error_no_return("Could not determine if converted file already exists, proceeding to convert file regardless. Encountered error: ", e)
        return False, None


def get_pdf_filepath_for_upload(filepath:pathlib.Path) -> pathlib.Path:
    '''
    Determine which PDF filepath to use for upload - either from staging or converted directories

    Args:
        - filepath: pathlib.Path object of the file to be uploaded

    Returns:
        - pathlib.Path object of the PDF filepath to be uploaded

    Raises:
        - Exception: If the PDF filepath cannot be determined, the conversion fails, or the file cannot be uploaded
    '''
    try:
        if not filepath.suffix.lower() == '.pdf':
            converted_file_exists, converted_pdf_file_path = check_if_converted_file_exists(filepath.with_suffix(".pdf").name)
            if not converted_file_exists:
                pdf_filepath = prep_and_execute_unoconv_conversion(filepath, converted_pdf_file_path.parent)
            else:
                pdf_filepath = converted_pdf_file_path
            return pdf_filepath
        else:
            return filepath
    except Exception as e:
        handle_local_error("Could not get PDF filepath for upload, encountered error: ", e)


def ocr_file_list(staging_folder:pathlib.Path, file_list: list) -> bool:
    '''
    OCR a list of files from the staging folder

    Args:
        - staging_folder: pathlib.Path object of the staging folder
        - file_list: list of files to be OCR'ed

    Returns:
        - bool: True if the OCR process completed successfully, False otherwise
    
    Raises:
        - Exception: If the staging folder cannot be determined, the file list cannot be determined, or the OCR process fails
    '''

    if not file_list or not isinstance(file_list, list) or len(file_list) == 0:
        print("No files to OCR in staging folder")
        return False
    
    for filename in file_list:

        try:
            full_file_path = staging_folder / filename
        except Exception as e:
            handle_error_no_return(f"Could not get full file path for {filename}, encountered error: ", e)
            continue
        
        try:    # Get PDF filepath for upload - either from staging or converted directories
            pdf_filepath = get_pdf_filepath_for_upload(full_file_path)
        except Exception as e:
            handle_error_no_return(f"Could not get PDF filepath for upload, encountered error: ", e)
            continue
        
        try:    # Get text from PDF
            txt_filepath = get_text_extract_from_pdf(pdf_filepath)
        except Exception as e:
            handle_error_no_return(f"Could not extract text from the PDF document, encountered error: ", e)
            continue

        try:    # Generate XML File
            _ = get_xml_from_text(txt_filepath)
        except Exception as e:
            handle_error_no_return(f"Could not generate XML file from text, encountered error: ", e)
            continue

    
    print("\n\nOCR completed\n\n")
    return True


def get_file_list_from_staging() -> tuple[pathlib.Path, list]:
    '''
    Get the list of files from the staging folder

    Returns:
        - tuple[pathlib.Path, list]: The staging folder and the list of files in the staging folder

    Raises:
        - Exception: If the staging folder cannot be determined, the file list cannot be determined, or the OCR process fails
    '''

    try:
        read_return = read_config(['upload_staging_folder'])
    except Exception as e:
        handle_local_error("Could not read upload_staging_folder from config.json, encountered error: ", e)
    
    try:
        staging_path = pathlib.Path(rf"{read_return['upload_staging_folder']}")
        normalized_staging_path = staging_path.resolve()
        return normalized_staging_path, os.listdir(normalized_staging_path)
    except Exception as e:
        handle_local_error("Could not list files in upload_staging_folder, encountered error: ", e)


def parse_arguments():

    try:
        parser = argparse.ArgumentParser(description="Docling Parser - Test Script")
    except Exception as e:
        handle_local_error("Could not create parser to parse_arguments(), proceeding with defaults. Encountered error: ", e)

    # Even if a parser object could not be created, a read_request will write & return defaults
    try:
        read_return = read_config(
            [
                'upload_staging_folder',
                'converted_pdfs',
                'ocr_pdfs',
                'ocr_service_choice',
                'force_re_extract',
                'docling_pipeline',
                'docling_vlm_model',
                'docling_ocr_model',
                'docling_do_ocr',
                'docling_do_code_enrichment',
                'docling_do_formula_enrichment',
                'docling_do_table_structure',
                'docling_do_picture_classification',
                'docling_do_picture_description',
                'docling_table_structure_mode',
                'docling_do_cell_matching',
                'docling_cuda_use_flash_attention_2',
                'docling_force_full_page_ocr',
                'docling_num_threads'
            ]
        )
    except Exception as e:
        handle_error_no_return("Could not get config values from docling_parser_config.json, encountered error: ", e)

    if parser:
        parser.add_argument("--reset_to_defaults", action="store_true", default=False, help="Use default settings")
        parser.add_argument("--upload-dir", type=str, default=read_return['upload_staging_folder'], help="Specify the upload staging folder. Remembers previously set value. Default: ./upload_staging")
        parser.add_argument("--converted-pdfs", type=str, default=read_return['converted_pdfs'], help="Specify the converted PDFs folder. Remembers previously set value. Default: ./converted_pdfs")
        parser.add_argument("--ocr-pdfs", type=str, default=read_return['ocr_pdfs'], help="Specify the OCR PDFs folder. Remembers previously set value. Default: ./ocr_pdfs")
        parser.add_argument("--ocr-service", type=str, default=read_return['ocr_service_choice'], help="Specify the OCR service to be used. Remembers previously set value. Default: docling.")
        parser.add_argument("--force-re-extract", action="store_true", default=False, help="Specify whether to force re-extraction of text. Defaults to False.")
        parser.add_argument("--dl-pipeline", type=str, default=read_return['docling_pipeline'], help="Specify the Docling pipeline to be used. Remembers previously set value. Default: standard.")
        parser.add_argument("--dl-vlm-model", type=str, default=read_return['docling_vlm_model'], help="Specify the Docling VLM model to be used. Remembers previously set value. Default: smoldocling_transformers.")
        parser.add_argument("--dl-ocr-model", type=str, default=read_return['docling_ocr_model'], help="Specify the Docling OCR model to be used. Remembers previously set value. Default: easyocr.")
        parser.add_argument("--dl-do-ocr", action="store_true", default=read_return['docling_do_ocr'], help="Specify whether to perform OCR. Remembers previously set value. Default: True.")
        parser.add_argument("--dl-do-code-enrichment", action="store_true", default=read_return['docling_do_code_enrichment'], help="Specify whether to perform code enrichment. Remembers previously set value. Default: False.")
        parser.add_argument("--dl-do-formula-enrichment", action="store_true", default=read_return['docling_do_formula_enrichment'], help="Specify whether to perform formula enrichment. Remembers previously set value. Default: False.")
        parser.add_argument("--dl-do-table-structure", action="store_true", default=read_return['docling_do_table_structure'], help="Specify whether to perform table structure. Remembers previously set value. Default: True.")
        parser.add_argument("--dl-do-picture-classification", action="store_true", default=read_return['docling_do_picture_classification'], help="Specify whether to perform picture classification. Remembers previously set value. Default: False.")
        parser.add_argument("--dl-do-picture-description", action="store_true", default=read_return['docling_do_picture_description'], help="Specify whether to perform picture description. Remembers previously set value. Default: False.")
        parser.add_argument("--dl-table-structure-mode", type=str, default=read_return['docling_table_structure_mode'], help="Specify the Docling table structure mode to be used. Remembers previously set value. Default: accurate.")
        parser.add_argument("--dl-do-cell-matching", action="store_true", default=read_return['docling_do_cell_matching'], help="Specify whether to perform cell matching. Remembers previously set value. Default: True.")
        parser.add_argument("--dl-cuda-use-flash-attention-2", action="store_true", default=read_return['docling_cuda_use_flash_attention_2'], help="Specify whether to use flash attention 2. Remembers previously set value. Default: False.")
        parser.add_argument("--dl-force-full-page-ocr", action="store_true", default=read_return['docling_force_full_page_ocr'], help="Specify whether to force full page OCR. Remembers previously set value. Default: False.")
        parser.add_argument("--dl-num-threads", type=int, default=read_return['docling_num_threads'], help="Specify the number of threads to be used. Remembers previously set value. Default: 4.")

        
        args = parser.parse_args()
        # print(f"\n\nparser.parse_args():\n\n{args}\n\n")

        if args.reset_to_defaults:
            print("\n\nLoading with Safe Defaults\n\n")
            try:
                # Empty docling_parser_config.json
                with open('docling_parser_config.json', 'w') as file:
                    json.dump({}, file, indent=4)
                
                # Set defaults by triggering read on an empty file
                read_config([
                    'upload_staging_folder',
                    'converted_pdfs',
                    'ocr_pdfs',
                    'ocr_service_choice',
                    'force_re_extract',
                    'docling_pipeline',
                    'docling_vlm_model',
                    'docling_ocr_model',
                    'docling_do_ocr',
                    'docling_do_code_enrichment',
                    'docling_do_formula_enrichment',
                    'docling_do_table_structure',
                    'docling_do_picture_classification',
                    'docling_do_picture_description',
                    'docling_table_structure_mode',
                    'docling_do_cell_matching',
                    'docling_cuda_use_flash_attention_2',
                    'docling_force_full_page_ocr',
                    'docling_num_threads'
                ])
            except Exception as e:
                handle_local_error("Could not reset hosts and ports in config.json, encountered error: ", e)

        else:
            try:
                write_config({
                    'upload_staging_folder':args.upload_dir,
                    'converted_pdfs':args.converted_pdfs,
                    'ocr_pdfs':args.ocr_pdfs,
                    'ocr_service_choice':args.ocr_service,
                    'force_re_extract':args.force_re_extract,
                    'docling_pipeline':args.dl_pipeline,
                    'docling_vlm_model':args.dl_vlm_model,
                    'docling_ocr_model':args.dl_ocr_model,
                    'docling_do_ocr':args.dl_do_ocr,
                    'docling_do_code_enrichment':args.dl_do_code_enrichment,
                    'docling_do_formula_enrichment':args.dl_do_formula_enrichment,
                    'docling_do_table_structure':args.dl_do_table_structure,
                    'docling_do_picture_classification':args.dl_do_picture_classification,
                    'docling_do_picture_description':args.dl_do_picture_description,
                    'docling_table_structure_mode':args.dl_table_structure_mode,
                    'docling_do_cell_matching':args.dl_do_cell_matching,
                    'docling_cuda_use_flash_attention_2':args.dl_cuda_use_flash_attention_2,
                    'docling_force_full_page_ocr':args.dl_force_full_page_ocr,
                    'docling_num_threads':args.dl_num_threads
                })
            except Exception as e:
                handle_local_error("Could not write hosts and ports to config.json, encountered error: ", e)

        return args


def main():
    print("\n\nStarting Docling Parser\n\n")
    _ = parse_arguments()
    staging_folder, file_list = get_file_list_from_staging()
    ocr_file_list(staging_folder, file_list) 
    print("\n\nDocling Parser completed\n\n")

    
if __name__ == "__main__":
    main()