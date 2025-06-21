#!/usr/bin/env python3
import os
import json
import shutil
import pandas as pd
import argparse
from typing import List
from huggingface_hub import HfApi
from pathlib import Path

# Function to copy and renumber episodes
def copy_and_renumber_episodes(dataset_paths: List[str], combined_path: str):
    # Create necessary directories
    os.makedirs(os.path.join(combined_path, "data/chunk-000"), exist_ok=True)
    os.makedirs(os.path.join(combined_path, "videos/chunk-000/observation.images.front"), exist_ok=True)
    os.makedirs(os.path.join(combined_path, "videos/chunk-000/observation.images.local"), exist_ok=True)
    os.makedirs(os.path.join(combined_path, "videos/chunk-000/observation.images.wrist"), exist_ok=True)
    
    episode_offset = 0
    for dataset_path in dataset_paths:
        # Count episodes in current dataset
        episode_count = len([f for f in os.listdir(os.path.join(dataset_path, "data/chunk-000")) 
                           if f.endswith(".parquet")])
        
        # Copy episodes from current dataset
        for i in range(episode_count):
            src_file = f"{dataset_path}/data/chunk-000/episode_{i:06d}.parquet"
            dst_file = f"{combined_path}/data/chunk-000/episode_{i+episode_offset:06d}.parquet"
            
            # Read the parquet file, update episode_index if needed, and save
            df = pd.read_parquet(src_file)
            if 'episode_index' in df.columns:
                df['episode_index'] = i + episode_offset
            df.to_parquet(dst_file)
            
            # Copy corresponding videos
            for camera in ["front", "local", "wrist"]:
                src_video = f"{dataset_path}/videos/chunk-000/observation.images.{camera}/episode_{i:06d}.mp4"
                dst_video = f"{combined_path}/videos/chunk-000/observation.images.{camera}/episode_{i+episode_offset:06d}.mp4"
                if os.path.exists(src_video):
                    shutil.copy2(src_video, dst_video)
        
        episode_offset += episode_count
        


# Function to combine metadata
def combine_metadata(dataset_paths: List[str], combined_path: str):
    # Combine episodes.jsonl
    combined_episodes = []
    
    # Create metadata directory
    os.makedirs(os.path.join(combined_path, "meta"), exist_ok=True)
    
    episode_offset = 0
    for dataset_path in dataset_paths:
        # Read episodes from current dataset
        with open(f"{dataset_path}/meta/episodes.jsonl", "r") as f:
            for line in f:
                episode = json.loads(line)
                # Update episode index
                episode['episode_index'] = episode.get('episode_index', 0) + episode_offset
                combined_episodes.append(episode)
        
        # Update offset for next dataset
        episode_count = len([f for f in os.listdir(os.path.join(dataset_path, "data/chunk-000")) 
                           if f.endswith(".parquet")])
        episode_offset += episode_count
    
    # Write combined episodes.jsonl
    with open(f"{combined_path}/meta/episodes.jsonl", "w") as f:
        for episode in combined_episodes:
            f.write(json.dumps(episode) + "\n")
    
    # Combine episodes_stats.jsonl
    combined_stats = []
    
    episode_offset = 0
    for dataset_path in dataset_paths:
        # Read stats from current dataset
        with open(f"{dataset_path}/meta/episodes_stats.jsonl", "r") as f:
            for line in f:
                stats = json.loads(line)
                # Update episode index
                stats['episode_index'] = stats.get('episode_index', 0) + episode_offset
                combined_stats.append(stats)
        
        # Update offset for next dataset
        episode_count = len([f for f in os.listdir(os.path.join(dataset_path, "data/chunk-000")) 
                           if f.endswith(".parquet")])
        episode_offset += episode_count
    
    # Write combined episodes_stats.jsonl
    with open(f"{combined_path}/meta/episodes_stats.jsonl", "w") as f:
        for stats in combined_stats:
            f.write(json.dumps(stats) + "\n")
    
    # Update info.json
    with open(f"{dataset_paths[0]}/meta/info.json", "r") as f:
        info = json.load(f)
    
    total_episodes = 0
    total_frames = 0
    total_videos = 0
    for dataset_path in dataset_paths:
        with open(f"{dataset_path}/meta/info.json", "r") as f:
            info2 = json.load(f)
            total_episodes += info2["total_episodes"]
            total_frames += info2["total_frames"]
            total_videos += info2["total_videos"]
    
    # Update counts and ensure codebase_version exists
    info["total_episodes"] = total_episodes
    info["total_frames"] = total_frames
    info["total_videos"] = total_videos
    info["splits"]["train"] = f"0:{total_episodes}"
    
    # Get codebase_version from first dataset if it exists, otherwise use a default
    codebase_version = info2.get("codebase_version", "0.1.0")
    info["codebase_version"] = codebase_version
    
    # Write updated info.json
    with open(f"{combined_path}/meta/info.json", "w") as f:
        json.dump(info, f, indent=4)
    
    # Copy tasks.jsonl (assuming they're the same)
    shutil.copy2(f"{dataset_paths[0]}/meta/tasks.jsonl", f"{combined_path}/meta/tasks.jsonl")

# Run the functions
def create_huggingface_tag(combined_path: str):
    """Create a tag on Hugging Face with the codebase version from info.json"""
    try:
        # Read the info.json to get codebase_version
        with open(os.path.join(combined_path, "meta", "info.json"), "r") as f:
            info = json.load(f)
        
        codebase_version = info.get("codebase_version")
        if not codebase_version:
            print("Warning: No codebase_version found in info.json")
            return
        
        # Extract the repo_id from the path
        # Assuming path format: /path/to/huggingface/username/repo_name
        repo_name = Path(combined_path).name
        username = Path(combined_path).parent.name
        repo_id = f"{username}/{repo_name}"
        
        # Create the tag
        hub_api = HfApi()
        hub_api.create_tag(repo_id, tag=codebase_version, repo_type="dataset")
        print(f"Created tag '{codebase_version}' for dataset '{repo_id}'")
    except Exception as e:
        print(f"Warning: Failed to create Hugging Face tag: {str(e)}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Combine multiple robot datasets into one')
    parser.add_argument('--combined-path', type=str, required=True,
                        help='Path where the combined dataset will be stored')
    parser.add_argument('--dataset-paths', type=str, nargs='+', required=True,
                        help='List of paths to the datasets to combine')
    parser.add_argument('--create-tag', action='store_true',
                        help='Create a tag on Hugging Face with the codebase version')
    
    args = parser.parse_args()
    
    print("Copying and renumbering episodes...")
    copy_and_renumber_episodes(args.dataset_paths, args.combined_path)
    print("Combining metadata...")
    combine_metadata(args.dataset_paths, args.combined_path)
    
    print("Done!")
    print(f"Combined dataset saved to: {args.combined_path}")
    
    if args.create_tag:
        create_huggingface_tag(args.combined_path)
