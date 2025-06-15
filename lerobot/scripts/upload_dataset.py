"""Script to upload a local dataset to the Hugging Face Hub."""

import argparse
from pathlib import Path
from typing import Optional

from datasets import Dataset, DatasetDict, load_dataset
from huggingface_hub import HfApi, create_repo


def upload_dataset(
    dataset_path: str,
    repo_id: str,
    private: bool = False,
    token: Optional[str] = None,
    revision: str = "main",
) -> None:
    """Upload a local dataset to the Hugging Face Hub.
    
    Args:
        dataset_path: Path to the local dataset directory or file
        repo_id: The repository ID on the Hub (format: username/dataset_name)
        private: Whether to create a private repository
        token: Hugging Face token. If not provided, will use the token from the CLI login
        revision: The git revision to push to
    """
    # Create the repository if it doesn't exist
    api = HfApi(token=token)
    try:
        create_repo(repo_id, repo_type="dataset", private=private, token=token)
    except Exception as e:
        if "already exists" not in str(e):
            raise e

    # Load the local dataset
    dataset_path = Path(dataset_path)
    if dataset_path.is_file():
        # Single file dataset
        extension = dataset_path.suffix.lower()
        if extension == ".csv":
            dataset = Dataset.from_csv(str(dataset_path))
        elif extension == ".json":
            dataset = Dataset.from_json(str(dataset_path))
        elif extension == ".parquet":
            dataset = Dataset.from_parquet(str(dataset_path))
        else:
            raise ValueError(f"Unsupported file format: {extension}")
        dataset_dict = DatasetDict({"train": dataset})
    else:
        # Directory containing multiple splits
        dataset_dict = load_dataset(str(dataset_path))

    # Push to hub
    dataset_dict.push_to_hub(
        repo_id,
        private=private,
        token=token,
        revision=revision,
    )
    print(f"Successfully uploaded dataset to: https://huggingface.co/datasets/{repo_id}")


def main():
    parser = argparse.ArgumentParser(description="Upload a local dataset to the Hugging Face Hub")
    parser.add_argument(
        "dataset_path",
        type=str,
        help="Path to the local dataset directory or file",
    )
    parser.add_argument(
        "repo_id",
        type=str,
        help="The repository ID on the Hub (format: username/dataset_name)",
    )
    parser.add_argument(
        "--private",
        action="store_true",
        help="Whether to create a private repository",
    )
    parser.add_argument(
        "--token",
        type=str,
        help="Hugging Face token. If not provided, will use the token from the CLI login",
    )
    parser.add_argument(
        "--revision",
        type=str,
        default="main",
        help="The git revision to push to",
    )

    args = parser.parse_args()
    upload_dataset(
        args.dataset_path,
        args.repo_id,
        private=args.private,
        token=args.token,
        revision=args.revision,
    )


if __name__ == "__main__":
    main()
