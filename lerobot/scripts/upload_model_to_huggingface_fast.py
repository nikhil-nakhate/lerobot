#!/usr/bin/env python3
import os
import argparse
import multiprocessing
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Tuple, Optional
from tqdm import tqdm
from huggingface_hub import HfApi, create_repo, upload_file


def validate_files(checkpoint_path: str, ignore_patterns: Optional[List[str]] = None) -> List[Tuple[str, str]]:
    """
    Validate and collect files for upload.
    Returns list of (local_path, remote_path) tuples.
    
    Args:
        checkpoint_path: Path to the checkpoint directory
        ignore_patterns: List of patterns to ignore (e.g. ['.git/*', '*.pyc'])
    """
    if not os.path.exists(checkpoint_path):
        raise ValueError(f"Checkpoint path {checkpoint_path} does not exist.")
    
    files_to_upload = []
    base_path = Path(checkpoint_path)
    
    def should_ignore(path: Path) -> bool:
        if not ignore_patterns:
            return False
        path_str = str(path.relative_to(base_path))
        for pattern in ignore_patterns:
            if pattern.endswith('/*'):
                if path_str.startswith(pattern[:-1]):
                    return True
            elif pattern.startswith('*.'):
                if path_str.endswith(pattern[1:]):
                    return True
        return False
    
    for path in base_path.rglob('*'):
        if path.is_file() and not should_ignore(path):
            relative_path = str(path.relative_to(base_path))
            files_to_upload.append((str(path), relative_path))
    
    return files_to_upload


def upload_single_file(args: Tuple[str, str, str]) -> Tuple[bool, str, Optional[str]]:
    """Upload a single file to HuggingFace.
    Returns: (success, file_path, error_message)
    """
    local_path, remote_path, repo_id = args
    try:
        api = HfApi()
        api.upload_file(
            path_or_fileobj=local_path,
            path_in_repo=remote_path,
            repo_id=repo_id,
            repo_type="model"
        )
        return True, local_path, None
    except Exception as e:
        return False, local_path, str(e)


def upload_model_checkpoint(checkpoint_path: str, repo_name: str, private: bool = False):
    """
    Upload a model checkpoint to Hugging Face Hub with parallel processing.
    
    Args:
        checkpoint_path: Path to the checkpoint directory
        repo_name: Name of the repository to create/use on Hugging Face
        private: Whether the repository should be private
    """
    # Initialize Hugging Face API and verify login
    api = HfApi()
    try:
        user_info = api.whoami()
        username = user_info['name']
        print(f"Logged in as: {username}")
    except Exception as e:
        raise RuntimeError(
            "You need to be logged in to Hugging Face to upload models. "
            "Please run 'huggingface-cli login' to log in."
        )
    
    # Create repository ID and validate files
    repo_id = f"{username}/{repo_name}"
    ignore_patterns = ['.git/*', '*.py', '__pycache__/*', '*.pyc', '.DS_Store']
    files_to_upload = validate_files(checkpoint_path, ignore_patterns)
    
    if not files_to_upload:
        raise ValueError(f"No files found in {checkpoint_path}")
    
    print(f"Found {len(files_to_upload)} files to upload")
    
    try:
        # Create repository if it doesn't exist
        create_repo(
            repo_id,
            repo_type="model",
            private=private,
            exist_ok=True
        )
        print(f"Repository {repo_id} is ready")
        
        # Prepare upload arguments
        upload_args = [(local, remote, repo_id) for local, remote in files_to_upload]
        
        # Calculate optimal number of workers based on CPU cores and file count
        max_workers = min(len(files_to_upload), multiprocessing.cpu_count() * 2)
        
        # Upload files in parallel with progress bar
        successful_uploads = 0
        failed_uploads = []
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(upload_single_file, args) for args in upload_args]
            
            with tqdm(total=len(files_to_upload), desc="Uploading files") as pbar:
                for future in as_completed(futures):
                    success, file_path, error = future.result()
                    if success:
                        successful_uploads += 1
                    else:
                        failed_uploads.append((file_path, error))
                    pbar.update(1)
        
        print(f"\nUpload Summary for {repo_id}:")
        print(f"✓ Successfully uploaded: {successful_uploads}/{len(files_to_upload)} files")
        
        if failed_uploads:
            print(f"✗ Failed uploads: {len(failed_uploads)} files")
            print("\nFailed uploads details:")
            for file_path, error in failed_uploads:
                print(f"  - {file_path}: {error}")
        else:
            print("✓ All files uploaded successfully!")
            
        print(f"\nView your model at: https://huggingface.co/{repo_id}")
            
    except Exception as e:
        print(f"Error during upload: {str(e)}")
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Upload model checkpoint to Hugging Face Hub")
    parser.add_argument(
        "--checkpoint-path",
        type=str,
        required=True,
        help="Path to the checkpoint directory"
    )
    parser.add_argument(
        "--repo-name",
        type=str,
        required=True,
        help="Name of the repository on Hugging Face"
    )
    parser.add_argument(
        "--private",
        action="store_true",
        help="Whether to make the repository private"
    )
    
    args = parser.parse_args()
    upload_model_checkpoint(args.checkpoint_path, args.repo_name, args.private)
