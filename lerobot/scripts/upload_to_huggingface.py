#!/usr/bin/env python3
import os
import sys
from huggingface_hub import HfApi, create_repo, upload_folder
import argparse
from datetime import datetime

def upload_to_huggingface(dataset_path, repo_name=None, private=False):
    """
    Upload the combined dataset to Hugging Face Hub.
    
    Args:
        dataset_path: Path to the combined dataset
        repo_name: Name of the repository to create/use on Hugging Face
        private: Whether the repository should be private
    """
    # Check if dataset path exists
    if not os.path.exists(dataset_path):
        print(f"Error: Dataset path {dataset_path} does not exist.")
        return False
    
    # Initialize Hugging Face API
    api = HfApi()
    
    # Check if user is logged in
    try:
        user_info = api.whoami()
        username = user_info['name']
        print(f"Logged in as: {username}")
    except Exception as e:
        print("Error: You need to be logged in to Hugging Face to upload datasets.")
        print("Please run 'huggingface-cli login' to log in.")
        return False
    
    # Generate repository name if not provided
    if not repo_name:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        repo_name = f"lerobot_combined_dataset_{timestamp}"
    
    # Create repository name with namespace
    repo_id = f"{username}/{repo_name}"
    
    try:
        # Create the repository
        print(f"Creating repository: {repo_id}")
        create_repo(repo_id, repo_type="dataset", private=private)
        
        # Upload the dataset
        print(f"Uploading dataset from {dataset_path} to {repo_id}...")
        upload_folder(
            folder_path=dataset_path,
            repo_id=repo_id,
            repo_type="dataset",
            ignore_patterns=[".git/*", "*.py", "__pycache__/*"]
        )
        
        print(f"Dataset successfully uploaded to https://huggingface.co/datasets/{repo_id}")
        return True
    
    except Exception as e:
        print(f"Error uploading dataset: {str(e)}")
        return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Upload combined dataset to Hugging Face Hub")
    parser.add_argument("--path", type=str, default="/home/nikhil/.cache/huggingface/lerobot/nikx-vla/lekiwi_data_combined",
                        help="Path to the combined dataset")
    parser.add_argument("--repo-name", type=str, default=None,
                        help="Name of the repository to create on Hugging Face")
    parser.add_argument("--private", action="store_true",
                        help="Make the repository private")
    
    args = parser.parse_args()
    
    # Create a README.md file with dataset information
    readme_path = os.path.join(args.path, "README.md")
    if not os.path.exists(readme_path):
        with open(readme_path, "w") as f:
            f.write("# Combined LeRobot Dataset\n\n")
            f.write("This dataset is a combination of multiple LeRobot datasets.\n\n")
            f.write("## Dataset Structure\n\n")
            f.write("- `data/`: Contains episode data in parquet format\n")
            f.write("- `meta/`: Contains metadata about the episodes\n")
            f.write("- `videos/`: Contains video recordings of the episodes\n\n")
            f.write("## Dataset Statistics\n\n")
            
            # Try to read info.json to get statistics
            try:
                import json
                info_path = os.path.join(args.path, "meta", "info.json")
                if os.path.exists(info_path):
                    with open(info_path, "r") as info_file:
                        info = json.load(info_file)
                        f.write(f"- Total Episodes: {info.get('total_episodes', 'N/A')}\n")
                        f.write(f"- Total Frames: {info.get('total_frames', 'N/A')}\n")
                        f.write(f"- Total Tasks: {info.get('total_tasks', 'N/A')}\n")
                        f.write(f"- Total Videos: {info.get('total_videos', 'N/A')}\n")
            except Exception as e:
                print(f"Warning: Could not read info.json: {str(e)}")
    
    # Upload the dataset
    success = upload_to_huggingface(args.path, args.repo_name, args.private)
    
    if success:
        print("Upload completed successfully!")
    else:
        print("Upload failed.")
        sys.exit(1)
