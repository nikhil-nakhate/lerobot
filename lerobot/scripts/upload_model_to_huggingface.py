#!/usr/bin/env python3
import os
import argparse
from pathlib import Path
from huggingface_hub import HfApi, create_repo, upload_folder

def upload_model_checkpoint(checkpoint_path: str, repo_name: str, private: bool = False):
    """
    Upload a model checkpoint to Hugging Face Hub.
    
    Args:
        checkpoint_path: Path to the checkpoint directory
        repo_name: Name of the repository to create/use on Hugging Face
        private: Whether the repository should be private
    """
    if not os.path.exists(checkpoint_path):
        raise ValueError(f"Checkpoint path {checkpoint_path} does not exist.")
    
    # Initialize Hugging Face API
    api = HfApi()
    
    # Check if user is logged in
    try:
        user_info = api.whoami()
        username = user_info['name']
        print(f"Logged in as: {username}")
    except Exception as e:
        raise RuntimeError(
            "You need to be logged in to Hugging Face to upload models. "
            "Please run 'huggingface-cli login' to log in."
        )
    
    # Create repository ID
    repo_id = f"{username}/{repo_name}"
    
    try:
        # Create repository if it doesn't exist
        create_repo(
            repo_id,
            repo_type="model",
            private=private,
            exist_ok=True
        )
        print(f"Repository {repo_id} is ready")
        
        # Upload the checkpoint folder
        upload_folder(
            folder_path=checkpoint_path,
            repo_id=repo_id,
            repo_type="model"
        )
        print(f"Successfully uploaded checkpoint to {repo_id}")
        
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
